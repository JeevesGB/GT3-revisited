#pragma once

#include "base/bytes.h"

namespace gt3r {

// Raw DEFLATE stream (no zlib/gzip header). Used by CORE.GT3.
Bytes inflate_raw(ByteSpan src, size_t expected_size);

// gzip member (RFC 1952). Used by compressed GT3.VOL entries.
Bytes inflate_gzip(ByteSpan src, size_t expected_size);

// gzip without a known output size (standalone course dumps / course import).
Bytes inflate_gzip_auto(ByteSpan src);

// zlib-wrapped deflate, for writing PNGs.
Bytes deflate_zlib(ByteSpan src);

// gzip member for writing standalone course files (.gz).
Bytes deflate_gzip(ByteSpan src);

} // namespace gt3r
