/* SOS-M7-C host adapter — POSIX termios bridge between sos-conformance
 * (subprocess port) and the disco-analyzer's USART1 VCP.
 *
 * Per SOS-05 §7 / PCDN-SOS-05-011 (C adapter language ratified).
 * Per PCDN-SOS-04-007 / SOS-05-007 (UART transport, 921600 8N1).
 * Per PCDN-SOS-04-014 (30-second per-vector wall-clock timeout).
 * Per PCDN-SOS-04-005 / SOS-05 inheritance (adapter-filtered done sentinel).
 *
 * Stdin -> vector JSON -> UART TX.
 * UART RX -> JSONL trace lines -> stdout (skipping the done sentinel).
 * Exit 0 on done sentinel; exit 2 on timeout; exit 3 on I/O error.
 *
 * Mirror of sos-m7-rust-host-driver (Rust). The byte-level wire framing,
 * exit-code policy, and sentinel-filtering rule are identical to the Rust
 * adapter; this is the C-language equivalent per PCDN-SOS-05-011.
 */

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/time.h>
#include <termios.h>
#include <unistd.h>

/* On macOS, non-standard (e.g. 921600) baud rates are set via the
 * IOSSIOSPEED ioctl AFTER tcsetattr applies a placeholder rate. The
 * required header lives in the IOKit framework but does not require
 * linking IOKitLib — only the ioctl number is needed. */
#if defined(__APPLE__)
#  include <IOKit/serial/ioss.h>
#endif

/* Default operational parameters (SOS-04/SOS-05 PCDN-resolved). */
#define DEFAULT_BAUD        921600
#define DEFAULT_TIMEOUT_SEC 30

/* Read-side buffer sizing. SELECT_TICK_USEC bounds how often the receive
 * loop re-checks the wall-clock deadline; 100 ms mirrors the Rust
 * adapter's serialport read timeout (lib.rs:135). */
#define SELECT_TICK_USEC  100000  /* 100 ms */
#define RX_CHUNK_SIZE     1024
#define LINE_INITIAL_CAP  1024
#define STDIN_INITIAL_CAP 4096
#define STDIN_MAX_CAP     (64 * 1024)  /* PCDN-SOS-04 vector ceiling */

/* The done sentinel field name per PCDN-SOS-04-005 / SOS-05 inheritance.
 * SOS-04 §7.3 reserves this name at the trace-format level so a real
 * TraceRecord cannot collide. */
static const char DONE_SENTINEL_FIELD[] = "__sos_done";

/* Forward decls for static helpers — placate -Wmissing-prototypes. */
static int  open_serial(const char *path, long baud);
static int  read_stdin_to_buf(uint8_t **buf, size_t *len);
static int  write_all(int fd, const uint8_t *buf, size_t len);
static int  pump(int serial_fd, const uint8_t *vector_buf, size_t vector_len, int timeout_sec);
static bool is_done_sentinel(const char *line, size_t len);
static void usage(FILE *out, const char *prog);
static int  set_serial_baud(int fd, long baud);

int main(int argc, char **argv) {
    const char *port = NULL;
    long        baud = DEFAULT_BAUD;
    int         timeout_sec = DEFAULT_TIMEOUT_SEC;

    static const struct option longopts[] = {
        { "port",    required_argument, NULL, 'p' },
        { "baud",    required_argument, NULL, 'b' },
        { "timeout", required_argument, NULL, 't' },
        { "help",    no_argument,       NULL, 'h' },
        { NULL, 0, NULL, 0 }
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "p:b:t:h", longopts, NULL)) != -1) {
        switch (opt) {
            case 'p': port = optarg; break;
            case 'b': baud = strtol(optarg, NULL, 10); break;
            case 't': timeout_sec = (int)strtol(optarg, NULL, 10); break;
            case 'h': usage(stdout, argv[0]); return 0;
            default:  usage(stderr, argv[0]); return 3;
        }
    }
    if (port == NULL) {
        fprintf(stderr, "sos-m7-c-host-driver: --port <path> required\n");
        usage(stderr, argv[0]);
        return 3;
    }
    if (timeout_sec <= 0) {
        fprintf(stderr, "sos-m7-c-host-driver: --timeout must be > 0\n");
        return 3;
    }

    if (baud <= 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: --baud must be a positive integer (got %ld)\n",
            baud);
        return 3;
    }

    int serial_fd = open_serial(port, baud);
    if (serial_fd < 0) {
        return 3;
    }

    uint8_t *vector_buf = NULL;
    size_t   vector_len = 0;
    if (read_stdin_to_buf(&vector_buf, &vector_len) != 0) {
        close(serial_fd);
        free(vector_buf);
        return 3;
    }
    if (vector_len == 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: empty stdin — no vector JSON to forward\n");
        close(serial_fd);
        free(vector_buf);
        return 3;
    }

    int rc = pump(serial_fd, vector_buf, vector_len, timeout_sec);
    free(vector_buf);
    close(serial_fd);
    return rc;
}

static void usage(FILE *out, const char *prog) {
    fprintf(out,
        "Usage: %s --port <PATH> [--baud %d] [--timeout %d]\n"
        "\n"
        "POSIX termios bridge between sos-conformance and the disco-analyzer\n"
        "board's USART1 VCP. Reads a vector JSON from stdin, forwards it to\n"
        "the firmware over UART, streams JSONL trace records back on stdout,\n"
        "and exits when the firmware emits its done sentinel.\n"
        "\n"
        "Discover the serial-device path at bench-bring-up time:\n"
        "  macOS:  ls /dev/tty.usbmodem*       (ST-Link VCP enumerates as usbmodem)\n"
        "  Linux:  ls /dev/ttyACM*             (ST-Link VCP enumerates as cdc_acm)\n"
        "\n"
        "Exit codes:\n"
        "  0  trace emitted cleanly; firmware sent done sentinel\n"
        "  2  per-vector timeout elapsed\n"
        "  3  I/O error (port open, stdin read, etc.)\n",
        prog, DEFAULT_BAUD, DEFAULT_TIMEOUT_SEC);
}

/* Apply baud to an already-opened serial fd. The two operating systems
 * we target take different paths for the rates SOS uses (PCDN-SOS-05-007
 * default is 921600, which is not in macOS's <termios.h> Bxxxx table):
 *
 *  - **macOS**: <termios.h> only defines Bxxxx up to B230400. For higher
 *    rates, set any defined placeholder rate via cfsetispeed/cfsetospeed
 *    + tcsetattr first, then issue an IOSSIOSPEED ioctl with the raw
 *    integer. This is the documented Darwin approach
 *    (<IOKit/serial/ioss.h>) and what every cross-platform serial
 *    library (libserialport, Python's pyserial) does internally.
 *  - **Linux (glibc)**: <termios.h> defines Bxxxx up to B4000000. We
 *    look up the Bxxxx constant in a switch; rates not in the table fall
 *    back to BOTHER + struct termios2 via ioctl(TCSETS2) — but for the
 *    SOS-05 supported set (9600..1000000) the constants are all present
 *    on modern glibc, so the switch path suffices.
 *
 * Returns 0 on success, -1 on failure (logs a diagnostic). */
static int set_serial_baud(int fd, long baud) {
    struct termios tio;
    if (tcgetattr(fd, &tio) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: tcgetattr failed: %s\n", strerror(errno));
        return -1;
    }

    /* Phase 1: install a baseline cfset*speed rate that the kernel
     * accepts. On macOS we use B9600 as a placeholder (will be overridden
     * by IOSSIOSPEED below). On Linux we install the real rate directly
     * via the Bxxxx constant. */
    speed_t placeholder;
    bool need_iossiospeed = false;

    switch (baud) {
#ifdef B9600
        case 9600:    placeholder = B9600;    break;
#endif
#ifdef B38400
        case 38400:   placeholder = B38400;   break;
#endif
#ifdef B57600
        case 57600:   placeholder = B57600;   break;
#endif
#ifdef B115200
        case 115200:  placeholder = B115200;  break;
#endif
#ifdef B230400
        case 230400:  placeholder = B230400;  break;
#endif
#ifdef B460800
        case 460800:  placeholder = B460800;  break;
#endif
#ifdef B921600
        case 921600:  placeholder = B921600;  break;
#endif
#ifdef B1000000
        case 1000000: placeholder = B1000000; break;
#endif
        default:
#if defined(__APPLE__)
            /* macOS: any defined rate will do for the placeholder;
             * IOSSIOSPEED will override. Use B9600 as the most universal. */
            placeholder = B9600;
            need_iossiospeed = true;
#else
            fprintf(stderr,
                "sos-m7-c-host-driver: baud %ld not in compile-time Bxxxx table; "
                "supported on this build: 9600/38400/57600/115200/230400/460800/921600/1000000\n",
                baud);
            return -1;
#endif
            break;
    }
    (void)need_iossiospeed;  /* silences -Wunused on non-Darwin */

    if (cfsetispeed(&tio, placeholder) != 0 ||
        cfsetospeed(&tio, placeholder) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: cfsetispeed/cfsetospeed failed: %s\n",
            strerror(errno));
        return -1;
    }
    if (tcsetattr(fd, TCSANOW, &tio) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: tcsetattr failed: %s\n", strerror(errno));
        return -1;
    }

#if defined(__APPLE__)
    /* Phase 2 (macOS only): use IOSSIOSPEED to install the actual baud
     * rate. Required for any rate above 230400. Harmless at lower rates
     * (the kernel accepts the same value we already set). */
    speed_t actual = (speed_t)baud;
    if (ioctl(fd, IOSSIOSPEED, &actual) == -1) {
        fprintf(stderr,
            "sos-m7-c-host-driver: IOSSIOSPEED(%ld) failed: %s\n",
            baud, strerror(errno));
        return -1;
    }
#endif

    return 0;
}

/* Open the serial device at `path`, configure raw 8N1 at `baud`, and
 * return a blocking fd (O_NONBLOCK is cleared after the initial open
 * since termios VMIN/VTIME does not gate non-blocking fds). Returns the
 * fd or -1 on error. */
static int open_serial(const char *path, long baud) {
    /* O_NONBLOCK during open avoids hanging on DCD-asserting devices; we
     * clear it immediately afterwards so subsequent read(2)s respect
     * VMIN/VTIME (or, in our case, block in select()). */
    int fd = open(path, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: failed to open serial port %s: %s\n",
            path, strerror(errno));
        return -1;
    }

    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags & ~O_NONBLOCK) < 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: failed to clear O_NONBLOCK on %s: %s\n",
            path, strerror(errno));
        close(fd);
        return -1;
    }

    struct termios tio;
    if (tcgetattr(fd, &tio) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: tcgetattr(%s) failed: %s\n",
            path, strerror(errno));
        close(fd);
        return -1;
    }

    /* cfmakeraw turns off canonical mode, echo, signal handling, parity
     * checking, output processing, and most input processing. Equivalent
     * to the explicit Rust `serialport` defaults (8N1, no flow control,
     * no parity, raw). */
    cfmakeraw(&tio);

    /* Belt-and-braces 8N1 + local + read-enable settings. cfmakeraw
     * already covers most of these; restating them defends against any
     * libc whose cfmakeraw leaves a stray flag in place. */
    tio.c_cflag |= (CLOCAL | CREAD);
    tio.c_cflag &= ~PARENB;
    tio.c_cflag &= ~CSTOPB;
    tio.c_cflag &= ~CSIZE;
    tio.c_cflag |= CS8;
    /* No hardware flow control (per PCDN-SOS-04-007). CRTSCTS is a
     * non-POSIX extension; only clear it if defined. */
#ifdef CRTSCTS
    tio.c_cflag &= ~CRTSCTS;
#endif

    /* VMIN/VTIME tuned for select()-driven reads: VMIN=0, VTIME=0 means
     * read() returns immediately with whatever bytes are available (or
     * zero if none). select() is the actual gate for "wait up to N ms".
     */
    tio.c_cc[VMIN]  = 0;
    tio.c_cc[VTIME] = 0;

    if (tcsetattr(fd, TCSANOW, &tio) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: tcsetattr(%s) failed: %s\n",
            path, strerror(errno));
        close(fd);
        return -1;
    }

    /* Apply the baud rate via the platform-appropriate path
     * (Bxxxx + tcsetattr on Linux; IOSSIOSPEED ioctl on macOS for
     * >230400 rates). */
    if (set_serial_baud(fd, baud) != 0) {
        close(fd);
        return -1;
    }

    /* Flush any stale bytes that may have been buffered before we opened
     * the port (e.g. boot-banner from a prior session). */
    (void)tcflush(fd, TCIOFLUSH);

    return fd;
}

/* Slurp stdin to EOF into a heap-allocated buffer. Returns 0 on success
 * (with *buf realloc'd to hold *len bytes, possibly NULL if len == 0),
 * or -1 on I/O error. Caller must free(*buf). Capped at STDIN_MAX_CAP
 * (64 KiB) per the PCDN-SOS-04 vector ceiling — wrapped vectors larger
 * than that don't fit in TRACE_RX_BUF on the firmware side either. */
static int read_stdin_to_buf(uint8_t **buf, size_t *len) {
    size_t   cap = STDIN_INITIAL_CAP;
    uint8_t *out = (uint8_t *)malloc(cap);
    if (out == NULL) {
        fprintf(stderr, "sos-m7-c-host-driver: out of memory reading stdin\n");
        *buf = NULL;
        *len = 0;
        return -1;
    }
    size_t used = 0;

    for (;;) {
        if (used == cap) {
            if (cap >= STDIN_MAX_CAP) {
                fprintf(stderr,
                    "sos-m7-c-host-driver: stdin exceeded %d byte vector ceiling\n",
                    STDIN_MAX_CAP);
                free(out);
                *buf = NULL;
                *len = 0;
                return -1;
            }
            size_t newcap = cap * 2;
            if (newcap > STDIN_MAX_CAP) {
                newcap = STDIN_MAX_CAP;
            }
            uint8_t *tmp = (uint8_t *)realloc(out, newcap);
            if (tmp == NULL) {
                fprintf(stderr,
                    "sos-m7-c-host-driver: out of memory growing stdin buffer\n");
                free(out);
                *buf = NULL;
                *len = 0;
                return -1;
            }
            out = tmp;
            cap = newcap;
        }
        ssize_t n = read(STDIN_FILENO, out + used, cap - used);
        if (n == 0) {
            break;  /* EOF */
        }
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            fprintf(stderr,
                "sos-m7-c-host-driver: read(stdin) failed: %s\n",
                strerror(errno));
            free(out);
            *buf = NULL;
            *len = 0;
            return -1;
        }
        used += (size_t)n;
    }

    *buf = out;
    *len = used;
    return 0;
}

/* write(2) loop — returns 0 on full write, -1 on error. */
static int write_all(int fd, const uint8_t *buf, size_t len) {
    size_t written = 0;
    while (written < len) {
        ssize_t n = write(fd, buf + written, len - written);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (n == 0) {
            /* Shouldn't happen on a blocking fd, but defend against it. */
            return -1;
        }
        written += (size_t)n;
    }
    return 0;
}

/* Test whether a JSONL line (without trailing newline) is the firmware's
 * done sentinel {"__sos_done":true}.
 *
 * Strategy: skip leading whitespace, require '{' next, then walk the
 * canonical token sequence permitting arbitrary inter-token whitespace.
 * The Rust adapter uses serde_json + a one-key object check; in C this
 * hand-rolled scanner is the simplest equivalent that tolerates
 * whitespace variations without dragging in a JSON library. Conservative
 * by construction: any deviation from {"__sos_done":true} (extra fields,
 * value != true, trailing garbage) returns false.
 */
static bool is_done_sentinel(const char *line, size_t len) {
    if (line == NULL || len == 0) {
        return false;
    }
    /* Cheap reject: most trace records don't carry the field name. */
    bool found = false;
    for (size_t i = 0; i + sizeof(DONE_SENTINEL_FIELD) - 2 < len; ++i) {
        if (memcmp(line + i, DONE_SENTINEL_FIELD,
                   sizeof(DONE_SENTINEL_FIELD) - 1) == 0) {
            found = true;
            break;
        }
    }
    if (!found) {
        return false;
    }

    size_t i = 0;

    /* skip leading whitespace */
    while (i < len && isspace((unsigned char)line[i])) {
        ++i;
    }
    if (i >= len || line[i] != '{') {
        return false;
    }
    ++i;
    while (i < len && isspace((unsigned char)line[i])) {
        ++i;
    }
    /* expect "__sos_done" */
    if (i >= len || line[i] != '"') {
        return false;
    }
    ++i;
    const size_t field_len = sizeof(DONE_SENTINEL_FIELD) - 1;  /* exclude NUL */
    if (i + field_len > len) {
        return false;
    }
    if (memcmp(line + i, DONE_SENTINEL_FIELD, field_len) != 0) {
        return false;
    }
    i += field_len;
    if (i >= len || line[i] != '"') {
        return false;
    }
    ++i;
    while (i < len && isspace((unsigned char)line[i])) {
        ++i;
    }
    if (i >= len || line[i] != ':') {
        return false;
    }
    ++i;
    while (i < len && isspace((unsigned char)line[i])) {
        ++i;
    }
    /* expect "true" */
    if (i + 4 > len || memcmp(line + i, "true", 4) != 0) {
        return false;
    }
    i += 4;
    while (i < len && isspace((unsigned char)line[i])) {
        ++i;
    }
    if (i >= len || line[i] != '}') {
        return false;
    }
    ++i;
    /* trailing whitespace only */
    while (i < len) {
        if (!isspace((unsigned char)line[i])) {
            return false;
        }
        ++i;
    }
    return true;
}

/* Forward the vector JSON to UART TX, then loop on UART RX collecting
 * JSONL lines. Each complete line is either filtered (done sentinel ->
 * clean exit) or echoed verbatim to stdout (with its trailing newline).
 *
 * Wall-clock deadline is enforced via gettimeofday(); select(2) is gated
 * to a SELECT_TICK_USEC tick so the deadline can be re-checked between
 * read bursts (mirrors the Rust adapter's 100 ms serialport timeout).
 *
 * Returns 0 on done sentinel; 2 on timeout; 3 on I/O error.
 */
static int pump(int serial_fd, const uint8_t *vector_buf, size_t vector_len, int timeout_sec) {
    /* Step 1: TX the vector JSON, appending a trailing '\n' if absent
     * (per SOS-04 §6.2.1 / SOS-05 inheritance — firmware reads bytes
     * into TRACE_RX_BUF until a balanced document terminated by '\n'). */
    if (write_all(serial_fd, vector_buf, vector_len) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: failed to write vector JSON to UART TX: %s\n",
            strerror(errno));
        return 3;
    }
    if (vector_len == 0 || vector_buf[vector_len - 1] != '\n') {
        uint8_t nl = '\n';
        if (write_all(serial_fd, &nl, 1) != 0) {
            fprintf(stderr,
                "sos-m7-c-host-driver: failed to write trailing newline to UART TX: %s\n",
                strerror(errno));
            return 3;
        }
    }
    /* tcdrain ensures the bytes hit the wire before we start expecting a
     * response. Non-fatal if it fails — some pseudo-tty backends return
     * ENOTTY here. */
    (void)tcdrain(serial_fd);

    /* Step 2: compute the wall-clock deadline. */
    struct timeval start;
    if (gettimeofday(&start, NULL) != 0) {
        fprintf(stderr,
            "sos-m7-c-host-driver: gettimeofday failed: %s\n", strerror(errno));
        return 3;
    }
    const long deadline_sec  = start.tv_sec + timeout_sec;
    const long deadline_usec = start.tv_usec;

    /* Step 3: line-accumulator for UART RX. Grows via realloc; uses the
     * '\n' boundary to dispatch each line. */
    size_t line_cap = LINE_INITIAL_CAP;
    char  *line_buf = (char *)malloc(line_cap);
    if (line_buf == NULL) {
        fprintf(stderr, "sos-m7-c-host-driver: out of memory for line buffer\n");
        return 3;
    }
    size_t line_len = 0;

    uint8_t rx_chunk[RX_CHUNK_SIZE];

    for (;;) {
        /* Re-check wall-clock deadline. */
        struct timeval now;
        if (gettimeofday(&now, NULL) != 0) {
            fprintf(stderr,
                "sos-m7-c-host-driver: gettimeofday failed: %s\n",
                strerror(errno));
            free(line_buf);
            return 3;
        }
        if (now.tv_sec > deadline_sec ||
            (now.tv_sec == deadline_sec && now.tv_usec >= deadline_usec)) {
            fprintf(stderr,
                "sos-m7-c-host-driver: timed out after %d s waiting for done sentinel on UART RX\n",
                timeout_sec);
            free(line_buf);
            return 2;
        }

        /* select() with a 100 ms tick. We don't gate on the *full*
         * remaining timeout in one shot because we want to remain
         * responsive to SIGINT etc., and to match the Rust adapter's
         * polling cadence. */
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(serial_fd, &rfds);
        struct timeval tick = { 0, SELECT_TICK_USEC };
        int sr = select(serial_fd + 1, &rfds, NULL, NULL, &tick);
        if (sr < 0) {
            if (errno == EINTR) {
                continue;
            }
            fprintf(stderr,
                "sos-m7-c-host-driver: select on UART RX failed: %s\n",
                strerror(errno));
            free(line_buf);
            return 3;
        }
        if (sr == 0) {
            continue;  /* tick elapsed with no data — back to deadline check */
        }

        ssize_t n = read(serial_fd, rx_chunk, sizeof(rx_chunk));
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) {
                continue;
            }
            fprintf(stderr,
                "sos-m7-c-host-driver: UART RX read error: %s\n",
                strerror(errno));
            free(line_buf);
            return 3;
        }
        if (n == 0) {
            /* Serial ports normally don't emit EOF. If they do, treat as
             * an unrecoverable RX error (matches the Rust adapter's
             * lib.rs:188 handling). */
            fprintf(stderr,
                "sos-m7-c-host-driver: serial port reached EOF before done sentinel arrived\n");
            free(line_buf);
            return 3;
        }

        /* Append to line buffer, dispatching on '\n'. */
        for (ssize_t k = 0; k < n; ++k) {
            uint8_t c = rx_chunk[k];

            /* Grow line buffer if needed (+1 for trailing NUL during
             * sentinel scan). */
            if (line_len + 1 >= line_cap) {
                size_t newcap = line_cap * 2;
                char *tmp = (char *)realloc(line_buf, newcap);
                if (tmp == NULL) {
                    fprintf(stderr,
                        "sos-m7-c-host-driver: out of memory growing line buffer\n");
                    free(line_buf);
                    return 3;
                }
                line_buf = tmp;
                line_cap = newcap;
            }
            line_buf[line_len++] = (char)c;

            if (c == '\n') {
                /* Inspect the line (excluding the trailing newline) for
                 * the done sentinel. */
                size_t content_len = line_len - 1;
                /* NUL-terminate for safety even though scanner is len-bounded. */
                line_buf[line_len] = '\0';

                if (is_done_sentinel(line_buf, content_len)) {
                    /* INV-S-PORT-12: sentinel is adapter-local; do NOT
                     * emit it on stdout. Clean exit. */
                    (void)fflush(stdout);
                    free(line_buf);
                    return 0;
                }

                /* Skip pure-whitespace lines (mirrors Rust adapter
                 * lib.rs:195 — line.trim().is_empty() continue). */
                bool blank = true;
                for (size_t b = 0; b < content_len; ++b) {
                    if (!isspace((unsigned char)line_buf[b])) {
                        blank = false;
                        break;
                    }
                }
                if (!blank) {
                    /* Pass through verbatim including the '\n'. */
                    if (fwrite(line_buf, 1, line_len, stdout) != line_len) {
                        fprintf(stderr,
                            "sos-m7-c-host-driver: failed to write trace record to stdout: %s\n",
                            strerror(errno));
                        free(line_buf);
                        return 3;
                    }
                    /* One flush per record per INV-S-SIM-7. */
                    (void)fflush(stdout);
                }

                line_len = 0;
            }
        }
    }
}
