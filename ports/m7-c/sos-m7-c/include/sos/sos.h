/* sos/sos.h — convenience umbrella header (PCDN-SOS-05-003 mitigation).
 *
 * Downstream consumers MAY `#include "sos/sos.h"` to pull in all five
 * module headers at once. The split-header surface
 * (sos/{kernel,event,trace,bsp,types}.h) remains the public API; this
 * file is the friction-reduction layer ratified at PCDN walk-through.
 */

#ifndef SOS_SOS_H
#define SOS_SOS_H

#include "sos/types.h"
#include "sos/event.h"
#include "sos/kernel.h"
#include "sos/trace.h"
#include "sos/bsp.h"

#endif /* SOS_SOS_H */
