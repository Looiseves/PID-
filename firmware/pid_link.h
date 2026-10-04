#ifndef PID_LINK_H
#define PID_LINK_H
#include <stddef.h>
#include <stdint.h>

/* Bind exactly one existing PID. Read/apply callbacks run in pid_link_poll(). */
typedef struct { float kp, ki, kd; } pid_link_gains;
typedef void (*pid_link_read_fn)(void *context, pid_link_gains *actual);
/* Return 1 only after all three coefficients have actually been applied. */
typedef int (*pid_link_apply_fn)(void *context, const pid_link_gains *requested);
typedef void (*pid_link_send_fn)(void *context, const char *bytes, size_t length);
typedef struct {
    void *context;
    pid_link_read_fn read;
    pid_link_apply_fn apply;
    pid_link_send_fn send;
    char loop[33], line[256], request_id[33], last_set_id[33];
    size_t used;
    unsigned dropping, pending;
    uint32_t revision, base;
    pid_link_gains known, candidate;
} pid_link;

int pid_link_init(pid_link *link, const char *loop, void *context,
                  pid_link_read_fn read, pid_link_apply_fn apply, pid_link_send_fn send);
/* Main context only: consume bytes copied from the UART RX ring buffer. */
void pid_link_feed(pid_link *link, const unsigned char *bytes, size_t length);
/* Call at a boundary safe for the existing PID, before its next calculation. */
void pid_link_poll(pid_link *link);
#endif
