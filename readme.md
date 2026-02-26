# THU E-RESERVE DOWNLOADER

This is a python crawler to download THU e-reserves from [https://ereserves.lib.tsinghua.edu.cn/](https://ereserves.lib.tsinghua.edu.cn/) and it is just a downloader which REQUIRES your WebVPN authorization.

## Usage

### Environment

```bash
pip install -r requirements.txt
```

### Download

```bash
python ereserve_downloader.py "<book_detail_page_id>"
```

`<book_detail_page_id>` is the last part of `https://ereserves.lib.tsinghua.edu.cn/bookDetail/<book_detail_page_id>`

The script will make two dirs: `downloads` for the original images downloaded and `output` for the ultimate PDF, which means you can delete `downloads` manually if you want.

## Disclaimer

This script is developed for the convenience of THU undergraduates using the PDF version of the e-reserves. Ultimate PDFs SHOULDN'T be used for any other purposes.


