"""Verify the firmware PING dispatch never invokes motor control."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FAKE=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#define USB_COMMAND_MAX 40
#define MOTOR_PROTOCOL_SIMPLEFOC 2
#define MOTOR_PROTOCOL 2
#define MOTOR_SIMPLEFOC_ID 'M'
#define MOTOR_AUTORUN_ENABLED 0
#define MOTOR_AUTORUN_USB_DIAGNOSTICS 1
#define SAMPLE_PERIOD_MS 10
#define DT_CHOSEN(x) 0
#define DEVICE_DT_GET(x) (&device)
#define K_MSEC(x) (x)
struct device { int unused; };
static struct device device;
struct motor_status { bool online,armed; int32_t angle_mrad,rpm_tenths; int error; };
static const char *input[8]; static int pos, len, motor_calls, cancel_calls;
static char last_command[40], output[512]; static size_t output_len;
static bool usb_rx_get(char *line) { if(pos>=len)return false; strcpy(line,input[pos++]); return true; }
static int usb_rx_init(const struct device *d) { (void)d; return 0; }
static int motor_command(const char *line) { motor_calls++; strcpy(last_command,line); return 0; }
static void motor_autorun_cancel(void) { cancel_calls++; }
static void motor_init(void) {} static void motor_autorun_init(void) {} static void motor_autorun_tick(void) {}
static void motor_tick(void) {} static void adc_inputs_sample(int32_t *v) { (void)v; }
static struct motor_status motor_get_status(void) { struct motor_status v={0}; return v; }
static int64_t k_uptime_get(void) { return 0; }
static uint32_t k_uptime_get_32(void) { return 0; }
static void k_sleep(int v) { (void)v; }
static int fake_printk(const char *fmt, ...) {
    va_list ap; va_start(ap,fmt); int n=vsnprintf(output+output_len,sizeof(output)-output_len,fmt,ap); va_end(ap);
    if(n>0) output_len+=(size_t)n; return n;
}
#define printk fake_printk
'''
HARNESS=r'''
#include "fake.h"
#define main firmware_main
#include "main.c"
#undef main
int main(void) {
    input[0]="PING"; len=1; pos=0; poll_commands();
    assert(motor_calls==0 && cancel_calls==0);
    assert(strstr(output,"pong") != NULL);
    input[0]="ARM"; len=1; pos=0; poll_commands();
    assert(motor_calls==1 && !strcmp(last_command,"ARM"));
    input[0]="STOP"; len=1; pos=0; poll_commands();
    assert(motor_calls==2 && cancel_calls==1 && !strcmp(last_command,"STOP"));
    return 0;
}
'''

class UsbDispatchTests(unittest.TestCase):
    def test_ping_does_not_touch_motor(self):
        compiler=shutil.which(os.environ.get('CC','gcc'))
        if not compiler: self.skipTest('gcc unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'fake.h').write_text(FAKE,encoding='utf-8')
            for name in ('adc_inputs.h','config.h','motor.h','motor_autorun.h','usb_rx.h',
                         'zephyr/device.h','zephyr/devicetree.h','zephyr/drivers/uart.h','zephyr/kernel.h','zephyr/sys/printk.h'):
                path=p/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('',encoding='utf-8')
            (p/'test.c').write_text(HARNESS,encoding='utf-8'); exe=p/'dispatch.exe'
            subprocess.run([compiler,'-std=c11','-I',str(p),'-I',str(ROOT/'src'),str(p/'test.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

if __name__=='__main__': unittest.main()
