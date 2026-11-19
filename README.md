# chibanatoru Downloader

A menu-driven command-line downloader for **Rule34** and **Danbooru**, built from the original `Rule34-Downloader.py`.
Each site has its own section (downloads + API settings), files are numbered in order, and images/videos are saved
in PNG/MP4 without losing quality.

> For adult users only. Follow your local laws and each site's terms of service and rate limits.

## Features

- **Two sites, separate sections** – Rule34 and Danbooru each have their own download menu and API settings.
- **Original quality** – downloads `file_url` (the original file), never the resized sample/preview.
- **Ordered names** – `1.png`, `2.png`, `3.mp4` ... (images and videos share one counter, in result order).
- **Images → PNG, lossless** – jpg/webp/etc. are re-saved as PNG with identical pixels (ICC profile kept). Files that are already PNG are untouched.
- **Videos → MP4** – `.mp4` is untouched. `.webm` and other video formats are remuxed to MP4 without re-encoding when possible; otherwise a visually lossless x264 encode is used.
- **Animated gif/webp → MP4** (visually lossless). Set `ANIMATED_TO_MP4 = False` at the top of the script to keep them as they are.
- **Other formats are still downloaded** – e.g. Danbooru ugoira `.zip` or `.swf` are saved unchanged with the same numbering (`4.zip`). If a conversion fails, the original file is kept.
- **Live stats** – files done, total size downloaded and current speed, plus a per-file progress bar.
- **Choose where to save** – press Enter to keep the current folder, `b` to open a folder picker, or paste any path. The choice is remembered.
- **Resume & retry** – interrupted downloads continue from the `.part` file; network errors are retried.
- **Pagination** – up to 5000 posts per search (Rule34: 1000 per page, Danbooru: 200 per page).
- **Optional CBZ** – packs the images of a folder into a `.cbz` archive.
- **Auto-install** – missing Python packages are installed automatically on first run.

## Requirements

- Python 3.8+
- Python packages: `requests`, `tqdm`, `colorama`, `pillow` – **installed automatically** on first run.
  If automatic install fails: `pip install requests tqdm colorama pillow`
- Optional: [ffmpeg](https://ffmpeg.org/) in your `PATH` for webm/gif → mp4 (e.g. `winget install ffmpeg`).
  Without it, those videos keep their original format.

## Usage

```
python chibanatoru-Downloader.py
```

```
========== chibanatoru Downloader ==========
1) Rule34 downloader
2) Danbooru downloader
0) Exit
```

Inside each site:

```
1) Download by tags
2) API settings
0) Back
```

Download flow: enter tags (space separated) → number of posts → save folder → CBZ yes/no.

Example tags: `cat_ears rating:g` (Danbooru), `some_tag` (Rule34).

## Output

Default save folder: `<your home>/Downloads/Art Downloaded`

```
Art Downloaded/
├── danbooru/
│   └── cat_ears_rating_g/
│       ├── 1.png
│       ├── 2.mp4
│       └── 3.png
└── rule34/
    └── some_tag/
        └── 1.png
```

Running the same search again continues numbering after the highest number in that folder
(already-downloaded posts are **not** detected, so they will be downloaded again with new numbers).

## API settings

Open the site's section → **API settings** to set, test or clear your credentials.

| Site     | What you need                    | Where to get it                                              |
|----------|----------------------------------|--------------------------------------------------------------|
| Rule34   | User ID + API key (required)     | `https://rule34.xxx/index.php?page=account&s=options`        |
| Danbooru | Username + API key (optional)    | `https://danbooru.donmai.us/profile` → API Keys              |

Notes:

- Danbooru's login is your **username**, not the numeric user ID (a numeric ID gives `401 Unauthorized`).
- Danbooru works without a key, but accounts without Gold are limited to **2 tags** per search.
- Credentials are stored in plain text in `config.json` next to the script. Do not share or commit it
  (add `config.json` to your `.gitignore`).

## Troubleshooting

| Message / symptom                           | Meaning / fix                                                                 |
|---------------------------------------------|-------------------------------------------------------------------------------|
| `401 Unauthorized` (Danbooru)               | Wrong login or key. Use the username and a valid API key (Test in API settings). |
| `Too many tags for this account`            | Free Danbooru accounts allow only 2 tags per search.                          |
| `API said: ...` (Rule34)                    | Missing or wrong API key / user ID.                                           |
| `No downloadable posts found`               | No results, or the posts have no public file (some Danbooru posts are restricted). |
| Videos stay `.webm`                         | ffmpeg is not installed or not in `PATH`.                                     |
| MP4 from webm won't play in some players    | The remux keeps the original VP9 video. Use VLC or a browser, or re-encode it. |

## License

Add your license here.
