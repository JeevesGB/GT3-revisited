#include "disc/volume.h"

#include "base/file.h"
#include "base/gzip.h"
#include "base/log.h"
#include "disc/iso9660.h"

#include <cstring>
#include <memory>
#include <set>

namespace gt3r {

Volume::Volume(Reader& file, u64 base_offset, u64 length) : file_(&file) {
    parts_.push_back({base_offset, length});
    read_toc(0);
    LOG_INFO("GT3.VOL: %zu files", entries_.size());
}

void Volume::add_part(u64 base_offset, u64 length) {
    if (parts_.size() >= 255) throw FormatError("GT3.VOL: too many volumes");
    parts_.push_back({base_offset, length});
    const size_t before = entries_.size();
    read_toc(u8(parts_.size() - 1));
    LOG_INFO("GT3.VOL: %zu more files from volume %zu", entries_.size() - before, parts_.size() - 1);
}

namespace {

void host_collect(const std::string& abs_dir, const std::string& rel, std::vector<Volume::Entry>& out) {
    for (const HostDirEntry& e : host_dir_entries(abs_dir)) {
        if (e.name == "." || e.name == "..") continue;
        const std::string child_abs = abs_dir + "/" + e.name;
        std::string child_rel = rel.empty() ? e.name : rel + "/" + e.name;
        for (char& c : child_rel)
            if (c >= 'A' && c <= 'Z') c = char(c - 'A' + 'a');
        if (e.dir) {
            host_collect(child_abs, child_rel, out);
            continue;
        }
        Volume::Entry ent;
        ent.host_path = child_abs;
        ent.compressed = false;
        if (child_rel.size() > 3 && child_rel.compare(child_rel.size() - 3, 3, ".gz") == 0) {
            ent.path = child_rel.substr(0, child_rel.size() - 3);
            ent.compressed = true;
        } else {
            ent.path = child_rel;
        }
        out.push_back(std::move(ent));
    }
}

std::string resolve_host_root(const std::string& root_dir) {
    std::string root = root_dir;
    while (!root.empty() && (root.back() == '/' || root.back() == '\\')) root.pop_back();
    if (host_is_directory(root + "/courses")) return root;
    if (host_is_directory(root + "/data/courses")) return root + "/data";
    if (host_is_directory(root + "/GT3") && host_is_directory(root + "/GT3/courses")) return root + "/GT3";
    return root;
}

Region guess_region_from_tree(const std::string& root) {
    auto has = [&](const char* sub) { return host_is_directory(root + sub); };
    if (auto b = read_host_file(root + "/disc/.region")) {
        std::string s(b->begin(), b->end());
        if (s.find("Japan") != std::string::npos || s.find("JP") != std::string::npos) return Region::Japan;
        if (s.find("Europe") != std::string::npos || s.find("EU") != std::string::npos) return Region::Europe;
        if (s.find("UK") != std::string::npos) return Region::Europe;
    }
    if (has("/courses/jp") || has("/courses/JP")) return Region::Japan;
    if (has("/courses/eu") || has("/courses/EU")) return Region::Europe;
    if (has("/courses/uk") || has("/courses/UK")) return Region::Europe;
    return Region::America;
}

} // namespace

std::unique_ptr<Volume> Volume::open_host(const std::string& root_dir) {
    const std::string root = resolve_host_root(root_dir);
    if (!host_is_directory(root)) throw FormatError("game folder not found: " + root_dir);

    auto vol = std::unique_ptr<Volume>(new Volume());
    vol->file_ = nullptr;
    host_collect(root, "", vol->entries_);
    for (size_t i = 0; i < vol->entries_.size(); ++i) vol->index_[vol->entries_[i].path] = i;

    Region r = guess_region_from_tree(root);
    vol->set_region(r);
    vol->set_identity(std::string("host-") + region_key(r), "HOST-FOLDER");

    LOG_INFO("Host game folder: %s (%zu files, region %s)", root.c_str(), vol->entries_.size(),
             region_key(r));
    if (vol->entries_.empty()) throw FormatError("no game files under " + root);
    return vol;
}

void Volume::read_toc(u8 part) {
    const Part& p = parts_[part];
    Bytes hdr = file_->read_at(p.base, 0x14);
    if (rd32(hdr, 0) != kMagic) throw FormatError("GT3.VOL: bad magic");
    u32 toc_size = rd32(hdr, 0x08);
    if (toc_size < 0x14 || toc_size > p.length) throw FormatError("GT3.VOL: bad toc size");
    Bytes toc = file_->read_at(p.base, toc_size);
    const size_t first = entries_.size();
    walk(toc, 0x14, "", 0, part);
    // A path the set already has stays the earlier volume's.
    std::vector<Entry> kept(entries_.begin(), entries_.begin() + ptrdiff_t(first));
    for (size_t i = first; i < entries_.size(); ++i)
        if (!index_.count(entries_[i].path)) index_[entries_[i].path] = kept.size(), kept.push_back(std::move(entries_[i]));
    entries_ = std::move(kept);
}

std::string Volume::node_name(ByteSpan toc, u32 offset) {
    std::string s;
    for (u32 i = offset; i < toc.size() && toc[i] != 0xFF; ++i) s.push_back(static_cast<char>(~toc[i]));
    return s;
}

void Volume::walk(ByteSpan toc, u32 node, const std::string& prefix, int depth, u8 part) {
    if (depth > 32) throw FormatError("GT3.VOL: directory tree too deep");
    u32 count = rd32(toc, node + 4);
    for (u32 i = 1; i < count; ++i) { // child 0 is the parent link
        u32 child = rd32(toc, node + 8 + i * 4);
        u32 word = rd32(toc, child);
        u32 flags = word >> 24;
        std::string name = prefix + node_name(toc, word & 0xFFFFFF);
        if (flags & 1) {
            walk(toc, child, name + "/", depth + 1, part);
            continue;
        }
        Entry e;
        e.path = std::move(name);
        e.sector = rd32(toc, child + 4);
        e.size = rd32(toc, child + 8);
        e.compressed = (flags & 2) != 0;
        e.stored_size = e.compressed ? rd32(toc, child + 12) : e.size;
        e.part = part;
        if (u64(e.sector) * kSectorSize + e.stored_size > parts_[part].length)
            throw FormatError("GT3.VOL: entry out of range: " + e.path);
        entries_.push_back(std::move(e));
    }
}

const Volume::Entry* Volume::find(const std::string& path) const {
    auto it = index_.find(path);
    return it == index_.end() ? nullptr : &entries_[it->second];
}

std::vector<std::string> Volume::list_dir(const std::string& dir) const {
    std::string prefix = dir.empty() || dir.back() == '/' ? dir : dir + "/";
    std::set<std::string> dirs;
    std::vector<std::string> files;
    for (auto it = index_.lower_bound(prefix); it != index_.end(); ++it) {
        const std::string& p = it->first;
        if (p.compare(0, prefix.size(), prefix) != 0) break;
        std::string rest = p.substr(prefix.size());
        if (auto slash = rest.find('/'); slash != std::string::npos)
            dirs.insert(rest.substr(0, slash + 1));
        else
            files.push_back(rest);
    }
    std::vector<std::string> out(dirs.begin(), dirs.end());
    out.insert(out.end(), files.begin(), files.end());
    return out;
}

Bytes Volume::read_raw(const Entry& e) const {
    if (!e.host_path.empty()) {
        auto data = read_host_file(e.host_path);
        if (!data) throw FormatError("host file missing: " + e.host_path);
        return *data;
    }
    if (!file_) throw FormatError("Volume: no reader");
    return file_->read_at(parts_[e.part].base + u64(e.sector) * kSectorSize, e.stored_size);
}

Bytes Volume::read(const Entry& e) const {
    Bytes raw = read_raw(e);
    if (!e.compressed) return raw;
    if (e.size) return inflate_gzip(raw, e.size);
    return inflate_gzip_auto(raw);
}

void Volume::read_range(const Entry& e, u64 offset, void* out, size_t len) const {
    if (e.compressed) throw FormatError("range read of compressed entry: " + e.path);
    if (!e.host_path.empty()) {
        auto data = read_host_file(e.host_path);
        if (!data) throw FormatError("host file missing: " + e.host_path);
        if (offset > data->size() || data->size() - offset < len)
            throw FormatError("range read out of bounds: " + e.path);
        std::memcpy(out, data->data() + offset, len);
        return;
    }
    if (offset > e.size || e.size - offset < len) throw FormatError("range read out of bounds: " + e.path);
    if (!file_) throw FormatError("Volume: no reader");
    file_->read_at(parts_[e.part].base + u64(e.sector) * kSectorSize + offset, out, len);
}

std::optional<Bytes> Volume::read_program() const {
    if (!program_reader_) return std::nullopt;
    try {
        return program_reader_();
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

} // namespace gt3r
