// Course viewer: course scenery (GTM1) from the disc region's course file, with the
// AI racing line and the road centre line drawn as ribbons on the road.

#include "app/app.h"
#include "app/screen_model_viewer.h"
#include "app/screen_registry.h"
#include "formats/course/course_model.h"

namespace gt3r {

namespace {

// Race courses first (r_ = reverse layout), then license-test variants (L_).
const char* const kCourses[] = {
    "tahitimaze_rec","assisi","capri","paris_rally","paris_tarmac", "newyork","hongkong",
};

// `lines`: the AI racing line and road centre line ribbons (shown, not exported).
scene::Model load_course_model(App& app, size_t i, bool lines) {
    Vfs* vfs = app.vfs();
    if (!vfs) throw FormatError("no disc loaded");
    std::string name = kCourses[i];
    std::string path = course_file_path(*vfs, name);
    if (auto data = path.empty() ? std::nullopt : vfs->read(path)) {
        course::CourseModelOptions opt;
        opt.ai_lines = lines;
        return course::build_course_model(*data, opt, name);
    }
    throw FormatError("course not found: " + name);
}

} // namespace

GT3R_REGISTER_SCREEN(courses, "courses", "Course viewer",
                     "Course scenery with the AI racing line (red) and road centre line (cyan).", 55, [] {
                         std::vector<std::string> names(std::begin(kCourses), std::end(kCourses));
                         return make_model_viewer(
                             "Courses", std::move(names), [](App& app, size_t i) { return load_course_model(app, i, true); },
                             {"courses", [](App& app, size_t i) { return load_course_model(app, i, false); }});
                     });

} // namespace gt3r
