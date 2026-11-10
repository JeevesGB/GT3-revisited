#include "formats/model/gtm1_encode.h"

#include <cmath>
#include <cstring>
#include <vector>

namespace gt3r::gtm1 {
namespace {

void w32(std::vector<u8>& b, size_t off, u32 v) {
    if (off + 4 > b.size()) b.resize(off + 4);
    std::memcpy(b.data() + off, &v, 4);
}
u32 rd32u(const u8* p) {
    u32 v;
    std::memcpy(&v, p, 4);
    return v;
}
float rdf(const u8* p, size_t o) {
    float f;
    std::memcpy(&f, p + o, 4);
    return f;
}
void wrf(u8* p, size_t o, float f) { std::memcpy(p + o, &f, 4); }

int vif_unpack_bytes(int vn, int vl, int count) {
    if (vn == 3 && vl == 3) return count * 2;
    int bits = (vl == 0 ? 32 : vl == 1 ? 16 : vl == 2 ? 8 : 5);
    int comps = vn + 1;
    int raw = (count * comps * bits) / 8;
    return (raw + 3) & ~3;
}

} // namespace

Bytes encode_simple_mesh(const float* positions, size_t vertex_count, const unsigned* indices,
                         size_t index_count, const char* /*name*/) {
    if (!positions || vertex_count == 0 || !indices || index_count < 3 || index_count % 3 != 0)
        throw FormatError("gtm1 encode: empty mesh");
    Bytes out(16);
    std::memcpy(out.data(), "GTM1", 4);
    w32(out, 4, 1);
    w32(out, 8, u32(vertex_count));
    w32(out, 12, u32(index_count));
    size_t base = out.size();
    out.resize(base + vertex_count * 12 + index_count * 4);
    std::memcpy(out.data() + base, positions, vertex_count * 12);
    std::memcpy(out.data() + base + vertex_count * 12, indices, index_count * 4);
    return out;
}

Bytes rewrite_gtm1_positions(ByteSpan template_gtm1, const float* positions, size_t vertex_count) {
    if (template_gtm1.size() < 16 || std::memcmp(template_gtm1.data(), "GTM1", 4) != 0)
        throw FormatError("not GTM1");
    Bytes out(template_gtm1.begin(), template_gtm1.end());
    std::vector<size_t> offs;
    for (size_t o = 16; o + 8 < out.size();) {
        u32 code = rd32u(out.data() + o);
        u32 cmd = (code >> 24) & 0x7f;
        if ((cmd & 0x60) != 0x60) {
            o += 4;
            continue;
        }
        int vn = int((cmd >> 2) & 3);
        int vl = int(cmd & 3);
        int num = int((code >> 16) & 0xff);
        int count = num ? num : 256;
        int addr = int(code & 0x3ff);
        int len = vif_unpack_bytes(vn, vl, count);
        size_t payload = o + 4;
        if (payload + size_t(len) > out.size()) {
            o += 4;
            continue;
        }
        if (addr == 0x00 && vn == 2 && vl == 0 && count > 0 && count < 4096) {
            bool ok = true;
            for (int i = 0; i < count && ok; ++i) {
                float x = rdf(out.data(), payload + size_t(i) * 16);
                float y = rdf(out.data(), payload + size_t(i) * 16 + 4);
                float z = rdf(out.data(), payload + size_t(i) * 16 + 8);
                if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) ok = false;
            }
            if (ok)
                for (int i = 0; i < count; ++i) offs.push_back(payload + size_t(i) * 16);
        }
        o = payload + size_t(len);
    }
    if (offs.size() != vertex_count) return {};
    for (size_t i = 0; i < offs.size(); ++i) {
        wrf(out.data(), offs[i] + 0, positions[i * 3 + 0]);
        wrf(out.data(), offs[i] + 4, positions[i * 3 + 1]);
        wrf(out.data(), offs[i] + 8, positions[i * 3 + 2]);
    }
    return out;
}

} // namespace gt3r::gtm1
