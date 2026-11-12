# Running GT3R from an extracted game folder

You do **not** need an ISO/CHD or to repack `GT3.VOL` for every course edit.

## Layout

Point GT3R at a folder that mirrors **VOL-relative** paths, for example:

```text
my-gt3-data/
  courses/
    US/
      trialmt.gz
      seattle.gz
      ...
    EU/
      ...
  cars/          (optional)
  menu/          (optional)
  ...
```

The [gt3-files](https://github.com/JeevesGB/gt3-files) tree works if you open its `data/` directory (or the repo root — GT3R looks for `data/courses` automatically).

`.gz` course files are decompressed on read (same as compressed VOL entries).

## How to open

1. Start GT3R  
2. **Open game folder**  
3. Choose your extracted data directory  

Or set in `config.ini`:

```ini
[game]
disc = C:/path/to/extracted/data
source = folder
```

## Course testing workflow

1. Convert a track in the Course viewer → `moddedtracks/converted/courses/US/name.gz`  
2. Copy/overwrite into your extracted `courses/US/name.gz`  
3. Restart course load / relaunch folder (no VOL rebuild)

Mods under `mods/*/files/` still override the host tree the same way they override a disc.
