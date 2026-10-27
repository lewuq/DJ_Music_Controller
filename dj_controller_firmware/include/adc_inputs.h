#pragma once
#include <stdint.h>
/* INT32_MIN means disabled or an unsuccessful conversion. Values are microvolts. */
void adc_inputs_sample(int32_t values[8]);
