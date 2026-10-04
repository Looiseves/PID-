#include "pid_link.h"
#include <ctype.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int identifier(const char *text) {
    size_t n = strlen(text);
    if (!n || n > 32) return 0;
    for (size_t i = 0; i < n; ++i)
        if (!(isalnum((unsigned char)text[i]) || text[i] == '_' || text[i] == '-')) return 0;
    return 1;
}
static int valid(pid_link_gains p) {
    return isfinite(p.kp) && isfinite(p.ki) && isfinite(p.kd) &&
           p.kp >= 0 && p.ki >= 0 && p.kd >= 0 && p.kp <= 10000 && p.ki <= 10000 && p.kd <= 10000;
}
static int equal(pid_link_gains a, pid_link_gains b) { return a.kp == b.kp && a.ki == b.ki && a.kd == b.kd; }
static void error(pid_link *p, const char *id, const char *code) {
    char packet[128];
    int n = snprintf(packet, sizeof packet, "@PID ERROR %s %s\n", id, code);
    if (n > 0 && (size_t)n < sizeof packet) p->send(p->context, packet, (size_t)n);
}
static void state(pid_link *p, const char *id) {
    char packet[256];
    int n = snprintf(packet, sizeof packet, "@PID STATE %s %" PRIu32 " %s %.9g %.9g %.9g\n",
                     id, p->revision, p->loop, (double)p->known.kp, (double)p->known.ki, (double)p->known.kd);
    if (n > 0 && (size_t)n < sizeof packet) p->send(p->context, packet, (size_t)n);
}
int pid_link_init(pid_link *p, const char *loop, void *context,
                  pid_link_read_fn read, pid_link_apply_fn apply, pid_link_send_fn send) {
    if (!p || !loop || !identifier(loop) || !read || !apply || !send) return 0;
    memset(p, 0, sizeof *p);
    p->context = context; p->read = read; p->apply = apply; p->send = send;
    strcpy(p->loop, loop);
    read(context, &p->known);
    return valid(p->known);
}
static void command(pid_link *p) {
    char marker[8], op[8], id[33], base[16], loop[33], a[40], b[40], c[40], extra[2];
    int count = sscanf(p->line, "%7s %7s %32s %15s %32s %39s %39s %39s %1s", marker, op, id, base, loop, a, b, c, extra);
    if (count < 3 || strcmp(marker, "@PID") || !identifier(id)) return;
    if (p->pending) { error(p, id, "BUSY"); return; }
    if (!strcmp(op, "GET") && count == 3) {
        strcpy(p->request_id, id); p->pending = 1; return;
    }
    if (strcmp(op, "SET") || count != 8) { error(p, id, "BAD_COMMAND"); return; }
    if (!strcmp(id, p->last_set_id)) { strcpy(p->request_id, id); p->pending = 1; return; }
    if (strcmp(loop, p->loop)) { error(p, id, "WRONG_LOOP"); return; }
    if (!*base || strlen(base) > 10) { error(p, id, "BAD_REVISION"); return; }
    for (const char *s = base; *s; ++s) if (!isdigit((unsigned char)*s)) { error(p, id, "BAD_REVISION"); return; }
    unsigned long long revision = strtoull(base, NULL, 10);
    if (revision > UINT32_MAX) { error(p, id, "BAD_REVISION"); return; }
    char *end;
    p->candidate.kp = strtof(a, &end); if (*end || end == a) { error(p, id, "BAD_VALUE"); return; }
    p->candidate.ki = strtof(b, &end); if (*end || end == b) { error(p, id, "BAD_VALUE"); return; }
    p->candidate.kd = strtof(c, &end); if (*end || end == c) { error(p, id, "BAD_VALUE"); return; }
    if (!valid(p->candidate)) { error(p, id, "BAD_VALUE"); return; }
    p->base = (uint32_t)revision;
    strcpy(p->request_id, id); p->pending = 2;
}
void pid_link_feed(pid_link *p, const unsigned char *bytes, size_t length) {
    for (size_t i = 0; i < length; ++i) {
        unsigned char byte = bytes[i];
        if (byte == '\n') {
            if (!p->dropping) { p->line[p->used] = 0; command(p); }
            p->used = p->dropping = 0;
        } else if (!p->dropping) {
            if (byte == 0 || byte > 127 || p->used + 1 >= sizeof p->line) { p->used = 0; p->dropping = 1; }
            else p->line[p->used++] = (char)byte;
        }
    }
}
void pid_link_poll(pid_link *p) {
    pid_link_gains actual;
    if (!p->pending) return;
    p->read(p->context, &actual);
    if (!valid(actual)) { error(p, p->request_id, "BAD_READBACK"); p->pending = 0; return; }
    if (!equal(actual, p->known)) {
        if (p->revision == UINT32_MAX) { error(p, p->request_id, "REVISION_FULL"); p->pending = 0; return; }
        p->known = actual; ++p->revision;
    }
    if (p->pending == 2) {
        if (p->base != p->revision) { error(p, p->request_id, "STALE"); p->pending = 0; return; }
        if (p->revision == UINT32_MAX) { error(p, p->request_id, "REVISION_FULL"); p->pending = 0; return; }
        if (!p->apply(p->context, &p->candidate)) { error(p, p->request_id, "REJECTED"); p->pending = 0; return; }
        p->read(p->context, &actual);
        if (!valid(actual)) { error(p, p->request_id, "BAD_READBACK"); p->pending = 0; return; }
        p->known = actual; ++p->revision;
        strcpy(p->last_set_id, p->request_id);
    }
    state(p, p->request_id);
    p->pending = 0;
}
