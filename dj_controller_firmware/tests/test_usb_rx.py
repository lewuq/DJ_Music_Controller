"""Exercise CDC RX registration, line framing, queue saturation and STOP priority."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
struct device { int unused; };
static struct device fake_device;
static bool ready = true, rx_enabled;
static int callback_error;
static void (*registered_cb)(const struct device *, void *);
static void *registered_data;
static unsigned char incoming[4096];
static int read_pos, read_end;
static bool device_is_ready(const struct device *d) { (void)d; return ready; }
static int uart_irq_callback_user_data_set(const struct device *d, void (*cb)(const struct device *, void *), void *data) {
    (void)d; registered_cb=cb; registered_data=data; return callback_error;
}
static void uart_irq_rx_enable(const struct device *d) { (void)d; rx_enabled=true; }
static int uart_irq_update(const struct device *d) { (void)d; return 1; }
static int uart_irq_rx_ready(const struct device *d) { (void)d; return read_pos<read_end; }
static int uart_fifo_read(const struct device *d, unsigned char *buf, int n) {
    (void)d; int remain=read_end-read_pos; if (n>remain) n=remain;
    memcpy(buf,incoming+read_pos,n); read_pos+=n; return n;
}
struct fake_queue { char items[8][40]; int count; };
#define K_MSGQ_DEFINE(name,size,n,align) struct fake_queue name
#define K_NO_WAIT 0
static int k_msgq_put(struct fake_queue *q, const void *p, int wait) {
    (void)wait; if (q->count==8) return -1; memcpy(q->items[q->count++],p,40); return 0;
}
static int k_msgq_get(struct fake_queue *q, void *p, int wait) {
    (void)wait; if (!q->count) return -1; memcpy(p,q->items[0],40); q->count--;
    memmove(q->items,q->items+1,(size_t)q->count*40); return 0;
}
static void k_msgq_purge(struct fake_queue *q) { q->count=0; }
'''
HARNESS = r'''
#include <assert.h>
#include "fake.h"
#include "usb_rx.c"
static void feed(const char *s) {
    size_t n=strlen(s); memcpy(incoming,s,n); read_pos=0; read_end=(int)n;
    assert(rx_enabled && registered_cb); registered_cb(&fake_device,registered_data);
    assert(read_pos==read_end);
}
int main(void) {
    char line[USB_COMMAND_MAX];
    ready=false; assert(usb_rx_init(&fake_device)==-ENODEV && !rx_enabled);
    ready=true; callback_error=-EIO; assert(usb_rx_init(&fake_device)==-EIO && !rx_enabled);
    callback_error=0; assert(usb_rx_init(&fake_device)==0 && rx_enabled);
    feed("PI"); assert(!usb_rx_get(line)); feed("NG\r\nARM\n");
    assert(usb_rx_get(line) && !strcmp(line,"PING"));
    assert(usb_rx_get(line) && !strcmp(line,"ARM")); assert(!usb_rx_get(line));
    feed("1234567890123456789012345678901234567890\nPING\n");
    assert(usb_rx_get(line) && !strcmp(line,"PING")); assert(!usb_rx_get(line));
    feed("A\nB\nC\nD\nE\nF\nG\nH\nSTOP\n");
    assert(usb_rx_get(line) && !strcmp(line,"STOP")); assert(!usb_rx_get(line));
    feed("ARM\nSPEED 4000\nME0\nPING\n");
    assert(usb_rx_get(line) && !strcmp(line,"ME0"));
    assert(usb_rx_get(line) && !strcmp(line,"PING")); assert(!usb_rx_get(line));
    return 0;
}
'''

class UsbRxTests(unittest.TestCase):
    def test_interrupt_driven_rx_and_complete_lines(self):
        compiler=shutil.which(os.environ.get('CC','gcc'))
        if not compiler: self.skipTest('gcc unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'fake.h').write_text(FAKE,encoding='utf-8')
            for name in ('device.h','drivers/uart.h','kernel.h'):
                path=p/'zephyr'/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('',encoding='utf-8')
            (p/'test.c').write_text(HARNESS,encoding='utf-8'); exe=p/'rx_test.exe'
            subprocess.run([compiler,'-std=c11','-I',str(p),
                            '-I',str(ROOT/'include'),'-I',str(ROOT/'src'),str(p/'test.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

if __name__=='__main__': unittest.main()
