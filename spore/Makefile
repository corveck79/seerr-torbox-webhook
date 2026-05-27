CC      = gcc
CFLAGS  = -shared -fPIC -O2 -std=gnu11 -Wall -Wextra -D_POSIX_C_SOURCE=200809L -D_LARGEFILE64_SOURCE
LDFLAGS = -ldl -lpthread -Wl,--version-script=spore.map
TARGET  = mycelium_spore.so

.PHONY: all clean

all: $(TARGET)

$(TARGET): spore.c
	$(CC) $(CFLAGS) -o $(TARGET) spore.c $(LDFLAGS)
	strip $(TARGET)

clean:
	rm -f $(TARGET)
