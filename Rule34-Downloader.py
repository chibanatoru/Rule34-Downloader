import os
import sys
import time
import zipfile
import requests
from tqdm import tqdm
from colorama import Fore, Style
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================== API Settings ==================
API_KEY = ""     #Please Enter API Key
USER_ID = ""     #Plase Enter User ID
# =================================================

def get_api_params(extra_params=None):
    params = {"api_key": API_KEY, "user_id": USER_ID}
    if extra_params:
        params.update(extra_params)
    return params

def download_media(tags, output_folder, limit=100, create_cbz=False):
    api_url = "https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&json=1"
    
    params = get_api_params({
        "tags": " ".join(tags),
        "limit": limit,
        "json": 1
    })
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        posts = response.json()
    except Exception as e:
        print(f"{Fore.RED}API Error: {e}{Style.RESET_ALL}")
        return
    
    num_posts = len(posts)
    print(f"\nFound {num_posts} posts. Starting download...\n")
    
    if num_posts == 0:
        print("No posts found.")
        return

    tag_folder = os.path.join(output_folder, "_".join(tags))
    os.makedirs(tag_folder, exist_ok=True)
    
    downloaded_files = []
    downloaded = 0

    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504, 429])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    
    for i, post in enumerate(posts, start=1):
        try:
            if not isinstance(post, dict): continue
            media_url = post.get("file_url")
            if not media_url: continue
                
            ext = os.path.splitext(media_url)[1].lower()
            if not ext:
                ext = '.jpg'
            media_name = f"{i:03d}{ext}"
            media_path = os.path.join(tag_folder, media_name)
            
            print(f"\n{Fore.CYAN}Downloading: {media_name}{Style.RESET_ALL}")

            # Resume support
            resume_header = {}
            file_mode = "wb"
            initial_size = 0

            if os.path.exists(media_path):
                initial_size = os.path.getsize(media_path)
                if initial_size > 0:
                    print(f"{Fore.YELLOW}Resuming from {initial_size / (1024*1024):.2f} MB...{Style.RESET_ALL}")
                    resume_header = {'Range': f'bytes={initial_size}-'}
                    file_mode = "ab"

            max_retries = 5
            for attempt in range(max_retries):
                try:
                    r = session.get(media_url, headers=resume_header, stream=True, timeout=120)
                    r.raise_for_status()

                    total_size = int(r.headers.get('content-length', 0))
                    if total_size == 0 and 'content-range' in r.headers:
                        content_range = r.headers.get('content-range', '')
                        if '/' in content_range:
                            total_size = int(content_range.split('/')[-1])

                    block_size = 1024 * 1024

                    with open(media_path, file_mode) as f:
                        with tqdm(total=total_size, initial=0, unit='B', unit_scale=True, unit_divisor=1024,
                                  desc="Progress", leave=True) as t:
                            
                            start_time = time.time()
                            downloaded_size = 0
                            
                            for chunk in r.iter_content(chunk_size=block_size):
                                if chunk:
                                    f.write(chunk)
                                    chunk_size = len(chunk)
                                    downloaded_size += chunk_size
                                    t.update(chunk_size)
                                    
                                    elapsed = time.time() - start_time
                                    if elapsed > 0.5 and downloaded_size > 0:
                                        speed = downloaded_size / elapsed
                                        t.set_postfix(speed=f"{speed/1024/1024:.2f} MB/s")

                    # Verify
                    final_size = os.path.getsize(media_path)
                    if final_size >= (initial_size + total_size * 0.95):
                        break
                    else:
                        raise Exception("Incomplete download")

                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"{Fore.YELLOW}Attempt {attempt+1} failed: {e}. Retrying in {2**attempt}s...{Style.RESET_ALL}")
                        time.sleep(2 ** attempt)
                        if os.path.exists(media_path):
                            initial_size = os.path.getsize(media_path)
                            resume_header = {'Range': f'bytes={initial_size}-'}
                            file_mode = "ab"
                        continue
                    else:
                        raise
            
            final_size_mb = os.path.getsize(media_path) / (1024 * 1024)
            print(f"{Fore.GREEN}✓ Completed: {media_name} | Size: {final_size_mb:.2f} MB{Style.RESET_ALL}")
            
            downloaded_files.append(media_path)
            downloaded += 1
            
        except Exception as e:
            print(f"{Fore.YELLOW}Warning: Failed to download {media_name}: {e}{Style.RESET_ALL}")
            continue
    
    print(f"\n{Fore.GREEN}Downloaded {downloaded} files successfully!{Style.RESET_ALL}")

    if create_cbz and downloaded_files:
        cbz_name = f"{'_'.join(tags)}.cbz"
        cbz_path = os.path.join(tag_folder, cbz_name)
        try:
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in tqdm(downloaded_files, desc="Creating CBZ", unit="file"):
                    zipf.write(file_path, os.path.basename(file_path))
            print(f"{Fore.GREEN}CBZ archive created: {cbz_path}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Failed to create CBZ: {e}{Style.RESET_ALL}")

def main():
    print("Rule34 Downloader - Improved Version")
    tags_str = input("Enter tags (separated by space): ")
    tags = tags_str.split()
    if not tags:
        print("No tags!")
        return
    
    limit_input = input("How many posts do you want to download? (max 1000): ") or "100"
    try:
        limit = int(limit_input)
        if limit > 1000:
            limit = 1000
    except ValueError:
        limit = 100
    
    output = input("Output folder (press Enter for 'downloads'): ") or "downloads"
    
    cbz_choice = input("Create CBZ archive? (y/n): ").strip().lower()
    create_cbz = cbz_choice in ['y', 'yes']
    
    download_media(tags, output, limit, create_cbz)

if __name__ == "__main__":
    main()
