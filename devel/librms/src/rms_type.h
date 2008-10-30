#ifndef __RMS_TYPE_H__
#define __RMS_TYPE_H__
#ifdef __cplusplus
extern "C" {
#endif
#include <stdlib.h>
#include <stdio.h>


typedef enum   rms_type_enum_def rms_type_enum;

enum rms_type_enum_def {rms_char_type , rms_float_type , rms_double_type , rms_bool_type , rms_byte_type , rms_int_type};

/* This *really* should not be exported ... */

typedef struct {
  rms_type_enum   rms_type;
  int             sizeof_ctype;
  
} __rms_type;

/*****************************************************************/

void          rms_type_free(void *);
__rms_type  * rms_type_alloc(rms_type_enum , int );
const void  * rms_type_copyc(const void * );

#ifdef __cplusplus
}
#endif
#endif
