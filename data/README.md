# Data

The CSV files in this folder are **committed to this repository** (26 files, about 318 MB; the largest are the two geolocation files at roughly 56 and 59 MB). A fresh clone therefore has everything needed to rebuild the databases.

## Source and license

- Dataset: *Brazilian E-Commerce Public Dataset by Olist*, provided by Olist (Kaggle: `olistbr/brazilian-ecommerce`).
- License: the dataset has its own license, shown on the Kaggle dataset page. These files are **not** covered by this repository's MIT license. Check the Kaggle license before reusing or redistributing them.
- `process/` and `final/` are derived from the original files by this project's pipeline. Check whether the dataset license also applies to derived data before redistributing them.

| Folder | Content |
|---|---|
| `raw/` | Original files from the Kaggle dataset. |
| `process/` | Cleaned tables (intermediate). |
| `final/` | Output of `utils/feature_engineering`; the input for `utils/create_sql` and `utils/qdrant`. |

## `/data` path

The scripts in `utils/` read files from the absolute path `/data/...`.
Create a symlink from the repo root:

```bash
sudo ln -s "$(pwd)/data" /data
```
