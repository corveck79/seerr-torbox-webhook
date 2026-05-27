/*
 * Mycelium Spore - Plex Interceptor
 *
 * LD_PRELOAD shared library that intercepts Plex file I/O for Mycelium stub
 * .mkv files and transparently streams real bytes from TorBox CDN via the
 * Mycelium Spore socket server.
 *
 * How it works:
 *   1. On open() of a .mkv file under MYCELIUM_MEDIA_PATH:
 *      - Read sibling .minfo file (token + CDN size)
 *      - Register fd as "virtual"
 *   2. fstat()  -> replace st_size with real CDN size
 *   3. read() / pread() at offset < HEADER_SIZE -> serve from stub file (MKV header)
 *   4. read() / pread() at offset >= HEADER_SIZE -> TCP request to Spore server
 *   5. mmap() on virtual fd -> ENODEV (forces Plex to fall back to read())
 *   6. close() -> deregister virtual fd
 *
 * Build:
 *   gcc -shared -fPIC -O2 -D_GNU_SOURCE -o mycelium_spore.so spore.c -ldl -pthread
 *
 * Inject into Plex:
 *   LD_PRELOAD=/spore/mycelium_spore.so
 *
 * Environment variables:
 *   MYCELIUM_SPORE_HOST  - Mycelium host  (default: mycelium)
 *   MYCELIUM_SPORE_PORT  - Spore TCP port (default: 8089)
 *   MYCELIUM_MEDIA_PATH  - Media root     (default: /data/media)
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netdb.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sendfile.h>
#include <sys/types.h>
#include <unistd.h>

/* ── Configuration ─────────────────────────────────────────────────────────── */
#define MKV_HEADER_SIZE  8192   /* bytes below this offset: served from stub */
#define MAX_FD           65536  /* indexed directly by fd number             */

/* ── Real glibc function pointers ──────────────────────────────────────────── */
static int     (*real_open)  (const char *, int, ...)           = NULL;
static int     (*real_open64)(const char *, int, ...)           = NULL;
static int     (*real_openat)(int, const char *, int, ...)      = NULL;
static ssize_t (*real_read)  (int, void *, size_t)              = NULL;
static ssize_t (*real_pread) (int, void *, size_t, off_t)       = NULL;
static int     (*real_fstat)  (int, struct stat *)              = NULL;
static int     (*real_fstat64)(int, struct stat64 *)            = NULL;
static int     (*real_stat)   (const char *, struct stat *)     = NULL;
static int     (*real_lstat)  (const char *, struct stat *)     = NULL;
static off_t   (*real_lseek)  (int, off_t, int)                 = NULL;
static int     (*real_close)  (int)                             = NULL;
static int     (*real_dup)    (int)                             = NULL;
static int     (*real_dup2)   (int, int)                        = NULL;
static void *  (*real_mmap)   (void *, size_t, int, int, int, off_t) = NULL;
static ssize_t (*real_sendfile)(int, int, off_t *, size_t)      = NULL;

/* ── Virtual fd table ───────────────────────────────────────────────────────── */
typedef struct {
    int    active;
    char   token[33];   /* 32 hex chars + NUL */
    off_t  cdn_size;
    off_t  seek_pos;    /* used by read() to track logical position */
} vfd_t;

static vfd_t            vfd_table[MAX_FD];
static pthread_rwlock_t vfd_lock = PTHREAD_RWLOCK_INITIALIZER;

/* Per-thread recursion guard (hash table avoids TLS early-init crashes).
   Hash collisions are safe: worst case a thread temporarily skips an intercept. */
#define HOOK_SLOTS 512
static volatile int _in_hook_tbl[HOOK_SLOTS];
static inline int  _get_in_hook(void) {
    return _in_hook_tbl[(unsigned long)pthread_self() % HOOK_SLOTS];
}
static inline void _set_in_hook(int v) {
    _in_hook_tbl[(unsigned long)pthread_self() % HOOK_SLOTS] = v;
}

/* Set to 1 after constructor completes - guards against early interception. */
static volatile int _spore_ready = 0;

/* ── Timestamped debug log ──────────────────────────────────────────────────── */
static void _spore_log(const char *fmt, ...) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    gmtime_r(&ts.tv_sec, &tm);
    char buf[640];
    int n = snprintf(buf, sizeof(buf),
        "SPORE [%02d:%02d:%02d.%03ld] pid=%d ",
        tm.tm_hour, tm.tm_min, tm.tm_sec,
        ts.tv_nsec / 1000000L,
        (int)getpid());
    va_list ap;
    va_start(ap, fmt);
    n += vsnprintf(buf + n, sizeof(buf) - (size_t)n, fmt, ap);
    va_end(ap);
    if (n > 0 && (size_t)n < sizeof(buf) - 1) {
        buf[n++] = '\n';
    }
    write(2, buf, (size_t)n);
}

/* ── Safe integer parser ────────────────────────────────────────────────────── */
static long long _parse_ll(const char *s) {
    long long r = 0;
    int neg = 0;
    if (!s) return 0;
    if (*s == '-') { neg = 1; s++; }
    while (*s >= '0' && *s <= '9') { r = r * 10 + (*s++ - '0'); }
    return neg ? -r : r;
}

/* Cached media path (read once at init, avoids repeated getenv in hot path) */
static char _cached_media_path[PATH_MAX] = "/data/media";

/* ── Config helpers ─────────────────────────────────────────────────────────── */
static const char *_spore_host(void) {
    const char *h = getenv("MYCELIUM_SPORE_HOST");
    return h ? h : "mycelium";
}
static const char *_spore_port(void) {
    const char *p = getenv("MYCELIUM_SPORE_PORT");
    return p ? p : "8089";
}
static const char *_media_path(void) {
    return _cached_media_path;
}

/* ── Helpers ────────────────────────────────────────────────────────────────── */

/* Returns 1 if path is under media root and ends in .mkv */
static int _is_mkv_candidate(const char *path) {
    if (!path) return 0;
    size_t n = strlen(path);
    if (n < 4) return 0;
    if (path[n-4] != '.' ||
        (path[n-3] | 0x20) != 'm' ||
        (path[n-2] | 0x20) != 'k' ||
        (path[n-1] | 0x20) != 'v') return 0;
    const char *mp = _media_path();
    return strncmp(path, mp, strlen(mp)) == 0;
}

/* Resolve full path from dirfd + possibly-relative path.
   out must be PATH_MAX bytes. Returns 1 on success. */
static int _resolve_path(int dirfd, const char *path, char *out) {
    if (path[0] == '/') {
        strncpy(out, path, PATH_MAX - 1);
        out[PATH_MAX - 1] = '\0';
        return 1;
    }
    /* Read dirfd's path from /proc/self/fd/<dirfd> */
    char fdlink[64];
    snprintf(fdlink, sizeof(fdlink), "/proc/self/fd/%d", dirfd);
    _set_in_hook(1);
    ssize_t r = readlink(fdlink, out, PATH_MAX - 1);
    _set_in_hook(0);
    if (r <= 0) return 0;
    out[r] = '\0';
    /* Append / + relative path */
    size_t dlen = (size_t)r;
    size_t flen = strlen(path);
    if (dlen + 1 + flen >= PATH_MAX) return 0;
    out[dlen] = '/';
    memcpy(out + dlen + 1, path, flen + 1);
    return 1;
}

/* Read .minfo sidecar (same dir, same stem, .minfo extension).
   Returns 1 on success; fills token_out (>=33 bytes) and size_out. */
static int _read_minfo(const char *mkv_path, char *token_out, off_t *size_out) {
    size_t n = strlen(mkv_path);
    char minfo_path[PATH_MAX];
    /* Replace last 4 chars (.mkv) with .minfo */
    if (n < 4 || n + 3 >= PATH_MAX) return 0;
    memcpy(minfo_path, mkv_path, n - 4);
    memcpy(minfo_path + n - 4, ".minfo", 7);

    _set_in_hook(1);
    int fd = real_open(minfo_path, O_RDONLY);
    _set_in_hook(0);
    if (fd < 0) return 0;

    char buf[256] = {0};
    _set_in_hook(1);
    ssize_t r = real_read(fd, buf, sizeof(buf) - 1);
    real_close(fd);
    _set_in_hook(0);
    if (r <= 0) return 0;

    token_out[0] = '\0';
    *size_out = 0;

    char *line = buf;
    while (line && *line) {
        if (strncmp(line, "token=", 6) == 0) {
            char *val = line + 6;
            char *end = strchr(val, '\n');
            size_t len = end ? (size_t)(end - val) : strlen(val);
            if (len > 0 && len <= 32) {
                memcpy(token_out, val, len);
                token_out[len] = '\0';
            }
        } else if (strncmp(line, "size=", 5) == 0) {
            *size_out = (off_t)_parse_ll(line + 5);
        }
        line = strchr(line, '\n');
        if (line) line++;
    }
    return token_out[0] != '\0';
}

/* Open TCP connection to Spore server. Returns socket fd or -1. */
static int _spore_connect(void) {
    struct addrinfo hints, *res, *rp;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family   = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    if (getaddrinfo(_spore_host(), _spore_port(), &hints, &res) != 0)
        return -1;

    int sock = -1;
    for (rp = res; rp; rp = rp->ai_next) {
        sock = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (sock < 0) continue;
        if (connect(sock, rp->ai_addr, rp->ai_addrlen) == 0) break;
        close(sock);
        sock = -1;
    }
    freeaddrinfo(res);
    return sock;
}

/* Send a range request to the Spore server.
   Protocol: "<token> <offset> <count>\n"  ->  "OK <actual>\n<bytes>"
   Returns bytes written to buf, or -1 on error. */
static ssize_t _spore_read(const char *token, off_t offset,
                            void *buf, size_t count) {
    int sock = _spore_connect();
    if (sock < 0) return -1;

    /* Send request */
    char req[128];
    int req_len = snprintf(req, sizeof(req), "%s %lld %zu\n",
                           token, (long long)offset, count);
    if (write(sock, req, req_len) != req_len) {
        close(sock);
        return -1;
    }

    /* Read response header (terminated by \n) */
    char hdr[64] = {0};
    int  hi = 0;
    while (hi < 63) {
        char c;
        if (read(sock, &c, 1) != 1) { close(sock); return -1; }
        hdr[hi++] = c;
        if (c == '\n') break;
    }

    if (strncmp(hdr, "OK ", 3) != 0) {
        close(sock);
        return -1;
    }
    ssize_t actual = (ssize_t)_parse_ll(hdr + 3);
    if (actual <= 0) { close(sock); return actual; }
    if (actual > (ssize_t)count) actual = (ssize_t)count;

    /* Read payload */
    ssize_t received = 0;
    while (received < actual) {
        ssize_t n = read(sock, (char *)buf + received,
                         (size_t)(actual - received));
        if (n <= 0) break;
        received += n;
    }
    close(sock);
    return received;
}

/* Scan /proc/self/fd and register any already-open virtual fds.
 * Called at init so streaming subprocesses (fork+exec'd by Plex) pick up fds
 * that were opened by the parent process before exec. */
static void _scan_inherited_fds(void) {
    DIR *d = opendir("/proc/self/fd");
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        int fd = (int)_parse_ll(e->d_name);
        if (fd < 0 || fd >= MAX_FD) continue;
        /* Skip the opendir fd itself */
        if (vfd_table[fd].active) continue;
        char linkpath[64];
        snprintf(linkpath, sizeof(linkpath), "/proc/self/fd/%d", fd);
        char target[PATH_MAX];
        ssize_t r = readlink(linkpath, target, PATH_MAX - 1);
        if (r <= 0) continue;
        target[r] = '\0';
        if (!_is_mkv_candidate(target)) continue;
        char token[33] = {0};
        off_t cdn_size = 0;
        if (_read_minfo(target, token, &cdn_size)) {
            pthread_rwlock_wrlock(&vfd_lock);
            vfd_table[fd].active   = 1;
            vfd_table[fd].cdn_size = cdn_size;
            vfd_table[fd].seek_pos = 0;
            strncpy(vfd_table[fd].token, token, 32);
            vfd_table[fd].token[32] = '\0';
            pthread_rwlock_unlock(&vfd_lock);
            _spore_log("inherited fd=%d token=%s size=%lld path=%s",
                       fd, token, (long long)cdn_size, target);
        }
    }
    closedir(d);
}

/* ── Library constructor ────────────────────────────────────────────────────── */
__attribute__((constructor))
static void _spore_init(void) {
    /* Initialise real_mmap and real_close FIRST: they can be called by dlsym
     * itself (mmap for lazy symbol resolution, close for fd cleanup), and our
     * interceptors must not return MAP_FAILED / -1 during that window. */
    real_mmap   = dlsym(RTLD_NEXT, "mmap");
    real_close  = dlsym(RTLD_NEXT, "close");
    real_open   = dlsym(RTLD_NEXT, "open");
    real_open64 = dlsym(RTLD_NEXT, "open64");
    real_openat = dlsym(RTLD_NEXT, "openat");
    real_read   = dlsym(RTLD_NEXT, "read");
    real_pread  = dlsym(RTLD_NEXT, "pread");
    real_fstat   = dlsym(RTLD_NEXT, "fstat");
    real_fstat64 = dlsym(RTLD_NEXT, "fstat64");
    real_stat     = dlsym(RTLD_NEXT, "stat");
    real_lstat    = dlsym(RTLD_NEXT, "lstat");
    real_lseek    = dlsym(RTLD_NEXT, "lseek");
    real_dup      = dlsym(RTLD_NEXT, "dup");
    real_dup2     = dlsym(RTLD_NEXT, "dup2");
    real_sendfile = dlsym(RTLD_NEXT, "sendfile");
    /* vfd_table is in BSS and already zero-initialised; memset is redundant
     * but kept as a belt-and-suspenders guard. */
    memset(vfd_table, 0, sizeof(vfd_table));

    /* Cache the media path from env at init time */
    const char *mp = getenv("MYCELIUM_MEDIA_PATH");
    if (mp && mp[0]) {
        strncpy(_cached_media_path, mp, PATH_MAX - 1);
        _cached_media_path[PATH_MAX - 1] = '\0';
    }

    _spore_ready = 1;

    _set_in_hook(1);
    _scan_inherited_fds();
    _set_in_hook(0);

    const char *host = getenv("MYCELIUM_SPORE_HOST");
    const char *port = getenv("MYCELIUM_SPORE_PORT");
    _spore_log("init done, media_path=%s host=%s port=%s",
        _cached_media_path,
        host ? host : "(unset)",
        port ? port : "(unset)");
}

/* ── Intercepted: open() ────────────────────────────────────────────────────── */
int open(const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = (flags & O_CREAT) ? va_arg(ap, mode_t) : 0;
    va_end(ap);

    if (_get_in_hook() || !_spore_ready) {
        /* Pre-init or recursive: use real pointer if available, else syscall. */
        if (real_open) return real_open(path, flags, mode);
        return (int)syscall(SYS_openat, AT_FDCWD, path, flags, (mode_t)mode);
    }
    if (!real_open)
        return (int)syscall(SYS_openat, AT_FDCWD, path, flags, (mode_t)mode);

    int fd = real_open(path, flags, mode);
    if (fd < 0 || fd >= MAX_FD) return fd;

    /* Log ANY .mkv open (even outside media_path) to catch transcoder using alternate paths */
    if (path) {
        size_t _pl = strlen(path);
        if (_pl >= 4 && (path[_pl-3]|0x20)=='m' && (path[_pl-2]|0x20)=='k' && (path[_pl-1]|0x20)=='v')
            _spore_log("open.any fd=%d %s", fd, path);
    }

    if (_is_mkv_candidate(path)) {
        _spore_log("open fd=%d %s", fd, path);
        char token[33] = {0};
        off_t cdn_size = 0;
        _set_in_hook(1);
        int ok = _read_minfo(path, token, &cdn_size);
        _set_in_hook(0);
        if (ok) {
            _spore_log("minfo ok fd=%d token=%s size=%lld", fd, token, (long long)cdn_size);
            pthread_rwlock_wrlock(&vfd_lock);
            vfd_table[fd].active   = 1;
            vfd_table[fd].cdn_size = cdn_size;
            vfd_table[fd].seek_pos = 0;
            strncpy(vfd_table[fd].token, token, 32);
            vfd_table[fd].token[32] = '\0';
            pthread_rwlock_unlock(&vfd_lock);
        } else {
            _spore_log("minfo FAIL fd=%d %s", fd, path);
        }
    }
    return fd;
}

/* ── Intercepted: openat() ──────────────────────────────────────────────────── */
int openat(int dirfd, const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = (flags & O_CREAT) ? va_arg(ap, mode_t) : 0;
    va_end(ap);

    if (!_spore_ready || _get_in_hook()) {
        if (real_openat) return real_openat(dirfd, path, flags, mode);
        return (int)syscall(SYS_openat, dirfd, path, flags, (mode_t)mode);
    }
    if (!real_openat)
        return (int)syscall(SYS_openat, dirfd, path, flags, (mode_t)mode);

    int fd = real_openat(dirfd, path, flags, mode);
    if (fd < 0 || fd >= MAX_FD) return fd;

    if (path) {
        /* Log any .mkv open via openat regardless of prefix */
        size_t _pl = strlen(path);
        if (_pl >= 4 && (path[_pl-3]|0x20)=='m' && (path[_pl-2]|0x20)=='k' && (path[_pl-1]|0x20)=='v')
            _spore_log("openat.any fd=%d dirfd=%d %s", fd, dirfd, path);

        char fullpath[PATH_MAX];
        if (_resolve_path(dirfd, path, fullpath) && _is_mkv_candidate(fullpath)) {
            _spore_log("openat fd=%d %s", fd, fullpath);
            char token[33] = {0};
            off_t cdn_size = 0;
            _set_in_hook(1);
            int ok = _read_minfo(fullpath, token, &cdn_size);
            _set_in_hook(0);
            if (ok) {
                _spore_log("minfo ok fd=%d token=%s size=%lld", fd, token, (long long)cdn_size);
                pthread_rwlock_wrlock(&vfd_lock);
                vfd_table[fd].active   = 1;
                vfd_table[fd].cdn_size = cdn_size;
                vfd_table[fd].seek_pos = 0;
                strncpy(vfd_table[fd].token, token, 32);
                vfd_table[fd].token[32] = '\0';
                pthread_rwlock_unlock(&vfd_lock);
            } else {
                _spore_log("minfo FAIL fd=%d %s", fd, fullpath);
            }
        }
    }
    return fd;
}

/* ── Intercepted: open64() ──────────────────────────────────────────────────── */
int open64(const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = (flags & O_CREAT) ? va_arg(ap, mode_t) : 0;
    va_end(ap);

    if (_get_in_hook() || !_spore_ready) {
        if (real_open64) return real_open64(path, flags, mode);
        if (real_open)   return real_open(path, flags, mode);
        return (int)syscall(SYS_openat, AT_FDCWD, path, flags | O_LARGEFILE, (mode_t)mode);
    }
    if (!real_open64 && !real_open)
        return (int)syscall(SYS_openat, AT_FDCWD, path, flags | O_LARGEFILE, (mode_t)mode);

    int fd = real_open64 ? real_open64(path, flags, mode) : real_open(path, flags, mode);
    if (fd < 0 || fd >= MAX_FD) return fd;

    if (_is_mkv_candidate(path)) {
        _spore_log("open64 fd=%d %s", fd, path);
        char token[33] = {0};
        off_t cdn_size = 0;
        _set_in_hook(1);
        int ok = _read_minfo(path, token, &cdn_size);
        _set_in_hook(0);
        if (ok) {
            _spore_log("minfo ok fd=%d token=%s size=%lld", fd, token, (long long)cdn_size);
            pthread_rwlock_wrlock(&vfd_lock);
            vfd_table[fd].active   = 1;
            vfd_table[fd].cdn_size = cdn_size;
            vfd_table[fd].seek_pos = 0;
            strncpy(vfd_table[fd].token, token, 32);
            vfd_table[fd].token[32] = '\0';
            pthread_rwlock_unlock(&vfd_lock);
        } else {
            _spore_log("minfo FAIL fd=%d %s", fd, path);
        }
    }
    return fd;
}

/* ── Intercepted: read() ────────────────────────────────────────────────────── */
ssize_t read(int fd, void *buf, size_t count) {
    if (_get_in_hook() || !_spore_ready || fd < 0 || fd >= MAX_FD) {
        if (real_read) return real_read(fd, buf, count);
        return (ssize_t)syscall(SYS_read, fd, buf, count);
    }
    if (!real_read)
        return (ssize_t)syscall(SYS_read, fd, buf, count);

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    off_t pos  = vfd_table[fd].seek_pos;
    char token[33];
    strncpy(token, vfd_table[fd].token, 33);
    pthread_rwlock_unlock(&vfd_lock);

    if (!active) return real_read(fd, buf, count);

    _spore_log("read fd=%d pos=%lld count=%zu", fd, (long long)pos, count);
    ssize_t r = _spore_read(token, pos, buf, count);
    if (r < 0) { errno = EIO; return -1; }
    if (r > 0) {
        pthread_rwlock_wrlock(&vfd_lock);
        if (vfd_table[fd].active) vfd_table[fd].seek_pos += r;
        pthread_rwlock_unlock(&vfd_lock);
    }
    return r;
}

/* ── Intercepted: pread() ───────────────────────────────────────────────────── */
ssize_t pread(int fd, void *buf, size_t count, off_t offset) {
    if (_get_in_hook() || !_spore_ready || fd < 0 || fd >= MAX_FD) {
        if (real_pread) return real_pread(fd, buf, count, offset);
        return (ssize_t)syscall(SYS_pread64, fd, buf, count, (off_t)offset);
    }
    if (!real_pread)
        return (ssize_t)syscall(SYS_pread64, fd, buf, count, (off_t)offset);

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    char token[33];
    strncpy(token, vfd_table[fd].token, 33);
    pthread_rwlock_unlock(&vfd_lock);

    if (!active) return real_pread(fd, buf, count, offset);

    _spore_log("pread fd=%d offset=%lld count=%zu", fd, (long long)offset, count);
    ssize_t r = _spore_read(token, offset, buf, count);
    if (r < 0) { errno = EIO; return -1; }
    return r;
}

/* pread64 is the same as pread on 64-bit Linux; provide wrapper for safety */
ssize_t pread64(int fd, void *buf, size_t count, off64_t offset) {
    return pread(fd, buf, count, (off_t)offset);
}

/* ── Intercepted: fstat() ───────────────────────────────────────────────────── */
int fstat(int fd, struct stat *st) {
    if (!real_fstat) {
        long r = syscall(SYS_fstat, fd, st);
        if (r < 0) { errno = (int)-r; return -1; }
        return 0;
    }
    int r = real_fstat(fd, st);
    if (r != 0 || !_spore_ready || fd < 0 || fd >= MAX_FD) return r;

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    off_t cdn_size = vfd_table[fd].cdn_size;
    pthread_rwlock_unlock(&vfd_lock);

    if (active && cdn_size > 0)
        st->st_size = cdn_size;
    return 0;
}

/* fstat64 on 64-bit Linux uses struct stat64 */
int fstat64(int fd, struct stat64 *st) {
    if (!real_fstat64) {
        long r = syscall(SYS_fstat, fd, st);
        if (r < 0) { errno = (int)-r; return -1; }
        return 0;
    }
    int r = real_fstat64(fd, st);
    if (r != 0 || !_spore_ready || fd < 0 || fd >= MAX_FD) return r;

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    off_t cdn_size = vfd_table[fd].cdn_size;
    pthread_rwlock_unlock(&vfd_lock);

    if (active && cdn_size > 0)
        st->st_size = cdn_size;
    return 0;
}

/* ── Path-based stat override ───────────────────────────────────────────────── */
/* Override st_size with cdn_size for stub .mkv files identified by .minfo */
static void _stat_override(const char *path, struct stat *st) {
    if (!_is_mkv_candidate(path)) return;
    char token[33] = {0};
    off_t cdn_size = 0;
    _set_in_hook(1);
    int ok = _read_minfo(path, token, &cdn_size);
    _set_in_hook(0);
    if (ok && cdn_size > 0)
        st->st_size = cdn_size;
}

/* ── Intercepted: stat() ────────────────────────────────────────────────────── */
int stat(const char *path, struct stat *st) {
    if (!real_stat) {
        long r = syscall(SYS_stat, path, st);
        if (r < 0) { errno = (int)-r; return -1; }
        return 0;
    }
    int r = real_stat(path, st);
    if (r == 0 && _spore_ready && !_get_in_hook())
        _stat_override(path, st);
    return r;
}

int stat64(const char *path, struct stat64 *st) {
    int r = stat(path, (struct stat *)st);
    return r;
}

/* ── Intercepted: lstat() ───────────────────────────────────────────────────── */
int lstat(const char *path, struct stat *st) {
    if (!real_lstat) {
        long r = syscall(SYS_lstat, path, st);
        if (r < 0) { errno = (int)-r; return -1; }
        return 0;
    }
    int r = real_lstat(path, st);
    if (r == 0 && _spore_ready && !_get_in_hook())
        _stat_override(path, st);
    return r;
}

int lstat64(const char *path, struct stat64 *st) {
    return lstat(path, (struct stat *)st);
}

/* ── Old-glibc stat wrappers (__xstat family) ───────────────────────────────── */
/* Plex binaries compiled against glibc < 2.33 call __xstat/__xstat64 instead
   of stat(). We intercept those too so the size override works. */
int __xstat(int ver, const char *path, struct stat *st) {
    static int (*real)(int, const char *, struct stat *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "__xstat");
    if (!real) { errno = ENOSYS; return -1; }
    int r = real(ver, path, st);
    if (r == 0 && _spore_ready && !_get_in_hook())
        _stat_override(path, st);
    return r;
}

int __xstat64(int ver, const char *path, struct stat64 *st) {
    static int (*real)(int, const char *, struct stat64 *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "__xstat64");
    if (!real) { errno = ENOSYS; return -1; }
    int r = real(ver, path, st);
    if (r == 0 && _spore_ready && !_get_in_hook())
        _stat_override(path, (struct stat *)st);
    return r;
}

int __lxstat(int ver, const char *path, struct stat *st) {
    static int (*real)(int, const char *, struct stat *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "__lxstat");
    if (!real) { errno = ENOSYS; return -1; }
    int r = real(ver, path, st);
    if (r == 0 && _spore_ready && !_get_in_hook())
        _stat_override(path, st);
    return r;
}

int __lxstat64(int ver, const char *path, struct stat64 *st) {
    static int (*real)(int, const char *, struct stat64 *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "__lxstat64");
    if (!real) { errno = ENOSYS; return -1; }
    int r = real(ver, path, st);
    if (r == 0 && _spore_ready && !_get_in_hook())
        _stat_override(path, (struct stat *)st);
    return r;
}

int __fxstat(int ver, int fd, struct stat *st) {
    static int (*real)(int, int, struct stat *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "__fxstat");
    if (!real) { errno = ENOSYS; return -1; }
    int r = real(ver, fd, st);
    if (r != 0 || !_spore_ready || fd < 0 || fd >= MAX_FD) return r;
    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    off_t cdn_size = vfd_table[fd].cdn_size;
    pthread_rwlock_unlock(&vfd_lock);
    if (active && cdn_size > 0) st->st_size = cdn_size;
    return 0;
}

int __fxstat64(int ver, int fd, struct stat64 *st) {
    static int (*real)(int, int, struct stat64 *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "__fxstat64");
    if (!real) { errno = ENOSYS; return -1; }
    int r = real(ver, fd, st);
    if (r != 0 || !_spore_ready || fd < 0 || fd >= MAX_FD) return r;
    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    off_t cdn_size = vfd_table[fd].cdn_size;
    pthread_rwlock_unlock(&vfd_lock);
    if (active && cdn_size > 0) st->st_size = cdn_size;
    return 0;
}

/* ── Intercepted: lseek() ───────────────────────────────────────────────────── */
off_t lseek(int fd, off_t offset, int whence) {
    if (!_spore_ready || fd < 0 || fd >= MAX_FD) {
        if (real_lseek) return real_lseek(fd, offset, whence);
        long r = syscall(SYS_lseek, fd, offset, whence);
        if (r < 0) { errno = (int)-r; return (off_t)-1; }
        return (off_t)r;
    }
    if (!real_lseek) {
        long r = syscall(SYS_lseek, fd, offset, whence);
        if (r < 0) { errno = (int)-r; return (off_t)-1; }
        return (off_t)r;
    }

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd].active;
    off_t pos  = vfd_table[fd].seek_pos;
    off_t size = vfd_table[fd].cdn_size;
    pthread_rwlock_unlock(&vfd_lock);

    if (!active) return real_lseek(fd, offset, whence);

    off_t new_pos;
    switch (whence) {
        case SEEK_SET: new_pos = offset;         break;
        case SEEK_CUR: new_pos = pos + offset;   break;
        case SEEK_END: new_pos = size + offset;  break;
        default: errno = EINVAL; return (off_t)-1;
    }
    if (new_pos < 0) { errno = EINVAL; return (off_t)-1; }

    pthread_rwlock_wrlock(&vfd_lock);
    if (vfd_table[fd].active) vfd_table[fd].seek_pos = new_pos;
    pthread_rwlock_unlock(&vfd_lock);
    return new_pos;
}

off64_t lseek64(int fd, off64_t offset, int whence) {
    return (off64_t)lseek(fd, (off_t)offset, whence);
}

/* ── Intercepted: dup() / dup2() ────────────────────────────────────────────── */
static void _copy_vfd(int oldfd, int newfd) {
    if (!_spore_ready || oldfd < 0 || oldfd >= MAX_FD ||
        newfd < 0 || newfd >= MAX_FD) return;
    pthread_rwlock_wrlock(&vfd_lock);
    if (vfd_table[oldfd].active) {
        vfd_table[newfd] = vfd_table[oldfd];
        _spore_log("dup oldfd=%d -> newfd=%d token=%s", oldfd, newfd, vfd_table[oldfd].token);
    }
    pthread_rwlock_unlock(&vfd_lock);
}

int dup(int oldfd) {
    int newfd = real_dup ? real_dup(oldfd) : (int)syscall(SYS_dup, oldfd);
    if (newfd >= 0) _copy_vfd(oldfd, newfd);
    return newfd;
}

int dup2(int oldfd, int newfd) {
    int r = real_dup2 ? real_dup2(oldfd, newfd) : (int)syscall(SYS_dup2, oldfd, newfd);
    if (r >= 0) _copy_vfd(oldfd, r);
    return r;
}

int dup3(int oldfd, int newfd, int flags) {
    int r = (int)syscall(SYS_dup3, oldfd, newfd, flags);
    if (r >= 0) _copy_vfd(oldfd, r);
    return r;
}

/* ── Intercepted: close() ───────────────────────────────────────────────────── */
int close(int fd) {
    if (_spore_ready && fd >= 0 && fd < MAX_FD) {
        pthread_rwlock_wrlock(&vfd_lock);
        if (vfd_table[fd].active) {
            _spore_log("close fd=%d token=%s", fd, vfd_table[fd].token);
            vfd_table[fd].active = 0;
        }
        pthread_rwlock_unlock(&vfd_lock);
    }
    if (real_close) return real_close(fd);
    return (int)syscall(SYS_close, fd);
}

/* ── Intercepted: sendfile() ────────────────────────────────────────────────── */
ssize_t sendfile(int out_fd, int in_fd, off_t *offset, size_t count) {
    if (!_spore_ready || in_fd < 0 || in_fd >= MAX_FD) {
        if (real_sendfile) return real_sendfile(out_fd, in_fd, offset, count);
        return (ssize_t)syscall(SYS_sendfile, out_fd, in_fd, offset, count);
    }

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[in_fd].active;
    off_t pos  = offset ? *offset : vfd_table[in_fd].seek_pos;
    char token[33];
    strncpy(token, vfd_table[in_fd].token, 33);
    pthread_rwlock_unlock(&vfd_lock);

    if (!active) {
        if (real_sendfile) return real_sendfile(out_fd, in_fd, offset, count);
        return (ssize_t)syscall(SYS_sendfile, out_fd, in_fd, offset, count);
    }

    _spore_log("sendfile in_fd=%d offset=%lld count=%zu", in_fd, (long long)pos, count);

    /* Fetch from CDN in chunks and write to out_fd */
    size_t remaining = count;
    ssize_t total = 0;
    char tmp[65536];
    while (remaining > 0) {
        size_t chunk = remaining < sizeof(tmp) ? remaining : sizeof(tmp);
        ssize_t r = _spore_read(token, pos, tmp, chunk);
        if (r <= 0) break;
        ssize_t w = write(out_fd, tmp, (size_t)r);
        if (w <= 0) break;
        pos += w;
        total += w;
        remaining -= (size_t)w;
    }
    if (offset) {
        *offset = pos;
    } else {
        pthread_rwlock_wrlock(&vfd_lock);
        if (vfd_table[in_fd].active) vfd_table[in_fd].seek_pos = pos;
        pthread_rwlock_unlock(&vfd_lock);
    }
    return total > 0 ? total : -1;
}

/* ── Intercepted: splice() ──────────────────────────────────────────────────── */
/* Plex uses splice() for zero-copy file-to-socket transfer, bypassing read(). */
ssize_t splice(int fd_in, loff_t *off_in, int fd_out, loff_t *off_out,
               size_t len, unsigned int flags) {
    if (!_spore_ready || fd_in < 0 || fd_in >= MAX_FD) {
        return (ssize_t)syscall(SYS_splice, fd_in, off_in, fd_out, off_out,
                                len, (long)flags);
    }

    pthread_rwlock_rdlock(&vfd_lock);
    int active = vfd_table[fd_in].active;
    off_t pos  = off_in ? (off_t)*off_in : vfd_table[fd_in].seek_pos;
    char token[33];
    strncpy(token, vfd_table[fd_in].token, 33);
    pthread_rwlock_unlock(&vfd_lock);

    if (!active) {
        return (ssize_t)syscall(SYS_splice, fd_in, off_in, fd_out, off_out,
                                len, (long)flags);
    }

    _spore_log("splice fd_in=%d offset=%lld len=%zu", fd_in, (long long)pos, len);

    size_t remaining = len;
    ssize_t total = 0;
    char tmp[65536];
    while (remaining > 0) {
        size_t chunk = remaining < sizeof(tmp) ? remaining : sizeof(tmp);
        ssize_t r = _spore_read(token, pos, tmp, chunk);
        if (r <= 0) break;
        ssize_t w = write(fd_out, tmp, (size_t)r);
        if (w <= 0) break;
        pos += w;
        total += w;
        remaining -= (size_t)w;
    }
    if (off_in) {
        *off_in = (loff_t)pos;
    } else {
        pthread_rwlock_wrlock(&vfd_lock);
        if (vfd_table[fd_in].active) vfd_table[fd_in].seek_pos = pos;
        pthread_rwlock_unlock(&vfd_lock);
    }
    return total > 0 ? total : -1;
}

/* ── Intercepted: mmap() ────────────────────────────────────────────────────── */
void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset) {
    if (!real_mmap) {
        /* Pre-init fallback: use direct syscall so library loading never breaks.
         * real_mmap is set as the very first dlsym call in _spore_init(), so
         * this path is only hit if mmap() is called before the constructor. */
        long r = syscall(SYS_mmap, addr, length, prot, flags, fd, (long)offset);
        if ((unsigned long)r >= (unsigned long)-4095L) {
            errno = (int)-r;
            return MAP_FAILED;
        }
        return (void *)r;
    }

    if (_spore_ready && fd >= 0 && fd < MAX_FD) {
        pthread_rwlock_rdlock(&vfd_lock);
        int active = vfd_table[fd].active;
        pthread_rwlock_unlock(&vfd_lock);
        if (active) {
            _spore_log("mmap ENODEV fd=%d length=%zu offset=%lld", fd, length, (long long)offset);
            errno = ENODEV;
            return MAP_FAILED;
        }
    }
    return real_mmap(addr, length, prot, flags, fd, offset);
}
