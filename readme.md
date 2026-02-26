# THU E-Reserve Downloader

This is a Python downloader for THU e-reserves from [https://ereserves.lib.tsinghua.edu.cn/](https://ereserves.lib.tsinghua.edu.cn/). It requires WebVPN authentication.

## Usage

### Environment

We recommend using an isolated Python environment (e.g., via `conda`) to avoid dependency conflicts; this README does not cover environment setup details.

```bash
pip install -r requirements.txt
```

### Download

```bash
python ereserve_downloader.py "<book_detail_page_id>"
```

`<book_detail_page_id>` is the trailing segment of `https://ereserves.lib.tsinghua.edu.cn/bookDetail/<book_detail_page_id>`.

The script creates two directories: `downloads` for the original images, and `output` for the final PDF. You can delete `downloads` afterwards if you want.

## Disclaimer

This script is developed for the convenience of THU undergraduates who need a PDF version of the e-reserves. The generated PDFs must not be used for any other purpose.

