#pragma once

// Experimental GTM1 mesh sidecar for tooling.
// Retail race scenery still uses template GTM1 + position import / future full encode.

#include "base/bytes.h"

#include <cstddef>

namespace gt3r::gtm1 {

// Writes experimental "GTM1" + version + mesh payload (not retail node programs).
Bytes encode_simple_mesh(const float* positions, size_t vertex_count, const unsigned* indices,
                         size_t index_count, const char* name = "mesh");

// True in-game path: copy template GTM1 bytes and overwrite position UNPACKs when counts match.
// Returns empty Bytes if counts do not match.
Bytes rewrite_gtm1_positions(ByteSpan template_gtm1, const float* positions, size_t vertex_count);

} // namespace gt3r::gtm1
