/* Host-only interoperability harness, never a board flashing target. */
#include "pid_link.h"
#include <stdio.h>
#include <string.h>
typedef struct { pid_link_gains actual; int applied; } fixture;
static void read_actual(void *ctx, pid_link_gains *p) { *p = ((fixture *)ctx)->actual; }
static int apply_actual(void *ctx, const pid_link_gains *p) {
    fixture *f = ctx;
    if (p->kp > 10) return 0;
    f->actual = *p; ++f->applied; return 1;
}
static void send_reply(void *ctx, const char *p, size_t length) { (void)ctx; fwrite(p, 1, length, stdout); }
int main(void) {
    fixture f = {{2, 1, .05f}, 0};
    pid_link link;
    if (!pid_link_init(&link, "steering", &f, read_actual, apply_actual, send_reply)) return 2;
    char line[4096];
    while (fgets(line, sizeof line, stdin)) {
        if (!strncmp(line, "EXTERNAL ", 9)) { sscanf(line + 9, "%f", &f.actual.kp); continue; }
        for (size_t i = 0; line[i]; ++i) pid_link_feed(&link, (const unsigned char *)line + i, 1);
        pid_link_poll(&link);
    }
    printf("APPLIES %d\n", f.applied);
    return 0;
}
