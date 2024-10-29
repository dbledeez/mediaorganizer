import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import re
import logging
import threading
import traceback
import sys
import queue
import hashlib
import requests
from pymediainfo import MediaInfo
import configparser  # For reading the config.ini file

# Configure logging
logging.basicConfig(
    filename='media_organizer.log',
    level=logging.DEBUG,  # Set to DEBUG for detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class MediaOrganizer:
    def __init__(self, log_queue, media_type, folders, progress_queue, config):
        self.media_type = media_type  # 'Movies' or 'TV Shows'
        self.folders = folders  # List of selected folders
        self.duplicates = []
        self.lock = threading.Lock()
        self.files_to_delete = []
        self.log_queue = log_queue
        self.progress_queue = progress_queue
        self.total_files = 0
        self.processed_files = 0
        # Read Sonarr settings from config
        self.sonarr_url = config.get('Sonarr', 'sonarr_url', fallback='http://localhost:8989/api/v3')
        self.sonarr_api_key = config.get('Sonarr', 'sonarr_api_key', fallback='')

    def log_message(self, message):
        logging.info(message.strip())
        self.log_queue.put(message)

    def sanitize_filename(self, filename):
        sanitized = re.sub(r'[<>:"/\\|?*]', '', filename)
        sanitized = sanitized.strip('. ')
        return sanitized

    def capitalize_title(self, title):
        return ' '.join(word.capitalize() for word in title.split())

    def is_video_file(self, filename):
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.mpg', '.mpeg', '.m4v']
        return os.path.splitext(filename)[1].lower() in video_extensions

    def is_subtitle_file(self, filename):
        subtitle_extensions = ['.srt', '.sub', '.idx', '.ssa', '.ass', '.vtt']
        return os.path.splitext(filename)[1].lower() in subtitle_extensions

    def is_hidden(self, filepath):
        if sys.platform == 'win32':
            try:
                attrs = os.stat(filepath).st_file_attributes
                return bool(attrs & 2)
            except AttributeError:
                return False
        else:
            return os.path.basename(filepath).startswith('.')

    def get_release_year(self, file_path):
        try:
            media_info = MediaInfo.parse(file_path)
            for track in media_info.tracks:
                if track.track_type == 'General':
                    for attr in ['recorded_date', 'encoded_date', 'tagged_date', 'file_last_modification_date', 'file_creation_date']:
                        date_value = getattr(track, attr, None)
                        if date_value:
                            match = re.search(r'(\d{4})', date_value)
                            if match:
                                year = match.group(1)
                                return year
        except Exception as e:
            self.log_message(f"Error extracting release year from '{file_path}': {e}\n")
            logging.error(f"Error extracting release year from '{file_path}': {e}")
            logging.error(traceback.format_exc())
        return None

    def get_series_name_from_metadata(self, file_path):
        try:
            media_info = MediaInfo.parse(file_path)
            for track in media_info.tracks:
                if track.track_type == 'General':
                    series_title = getattr(track, 'album', None)
                    if series_title:
                        return series_title
        except Exception as e:
            self.log_message(f"Error extracting series name from '{file_path}': {e}\n")
            logging.error(f"Error extracting series name from '{file_path}': {e}")
            logging.error(traceback.format_exc())
        return None

    def get_tv_show_release_year(self, series_title):
        try:
            url = f"https://api.tvmaze.com/singlesearch/shows"
            params = {'q': series_title}
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                premiere_date = data.get('premiered')
                if premiere_date:
                    year = premiere_date.split('-')[0]
                    return str(year)
        except Exception as e:
            self.log_message(f"Error fetching release year for '{series_title}': {e}\n")
            logging.error(f"Error fetching release year for '{series_title}': {e}")
            logging.error(traceback.format_exc())
        return None

    def parse_movie_title(self, filename):
        filename = re.sub(r'[\[\(\{].*?[\]\)\}]', '', filename)
        unwanted_terms = [
            '720p', '1080p', '2160p', '480p',
            'BRRip', 'BluRay', 'WEBRip', 'WEB-DL',
            'HDRip', 'DVDRip', 'DVDSCR', 'CAM',
            'XviD', 'x264', 'h264', 'H\.264', 'H264',
            'AAC', 'MP3', 'RARBG', 'YIFY', 'YTS', 'ETRG', 'Ganool',
            '10bit', '6CH', 'HEVC', 'HQ', 'HD', 'TS',
            'PROPER', 'NEW', 'PSA', 'CPG', 'GalaxyRG', '999MB',
            'Rip', 'DvD', 'DvDRip', 'x265', 'DivX', 'AMZN', 'WEB', 'WEB-DLRip',
            'NF', 'Remastered', 'Atmos', 'HC', 'HDCAM', 'Line', 'Subs',
            'EXTENDED', 'UNRATED', "Director's Cut", 'IMAX', 'Repack', 'READNFO',
            'FIX', 'V2', 'V3', 'FINAL', 'LIMITED',
        ]
        unwanted_pattern = r'\b(?:' + '|'.join(unwanted_terms) + r')\b'
        filename = re.sub(unwanted_pattern, '', filename, flags=re.IGNORECASE)
        filename = re.sub(r'\b(19|20)\d{2}\b', '', filename)
        filename = re.sub(r'[\.\-_\s]+', ' ', filename)
        filename = filename.strip()
        return filename

    def parse_tv_show_filename(self, filename):
        filename = re.sub(r'[\[\(\{].*?[\]\)\}]', '', filename)
        unwanted_terms = [
            '720p', '1080p', '2160p', '480p',
            'BRRip', 'BluRay', 'WEBRip', 'WEB-DL',
            'HDRip', 'DVDRip', 'DVDSCR', 'CAM',
            'XviD', 'x264', 'h264', 'H\.264', 'H264',
            'AAC', 'MP3', 'RARBG', 'YIFY', 'YTS', 'ETRG', 'Ganool',
            '10bit', '6CH', 'HEVC', 'HQ', 'HD', 'TS',
            'PROPER', 'NEW', 'PSA', 'CPG', 'GalaxyRG', '999MB',
            'Rip', 'DvD', 'DvDRip', 'x265', 'DivX', 'AMZN', 'WEB', 'WEB-DLRip',
            'NF', 'Remastered', 'Atmos', 'HC', 'HDCAM', 'Line', 'Subs',
            'EXTENDED', 'UNRATED', "Director's Cut", 'IMAX', 'Repack', 'READNFO',
            'FIX', 'V2', 'V3', 'FINAL', 'LIMITED',
        ]
        unwanted_pattern = r'\b(?:' + '|'.join(unwanted_terms) + r')\b'
        filename = re.sub(unwanted_pattern, '', filename, flags=re.IGNORECASE)
        filename = re.sub(r'[\.\-_\s]+', ' ', filename)
        filename = filename.strip()
        patterns = [
            r'^(.*?)[\s\.]+[sS](\d+)[\s\.]*[eE](\d+)',
            r'^(.*?)[\s\.]+(\d+)[xX](\d+)',
            r'^(.*?)[\s\.]+Season[\s\.]*(\d+)[\s\.]+Episode[\s\.]*(\d+)',
            r'^(.*?)\s*[.-]?\s*(\d{1,2})(\d{2})',  # e.g., 'Show 102' for S01E02
            r'^[sS](\d+)[eE](\d+)\s*(.*?)$',
        ]
        for pattern in patterns:
            match = re.match(pattern, filename, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    series_title = groups[0].strip()
                    season_num = groups[1]
                    episode_num = groups[2]
                elif len(groups) == 2:
                    series_title = ''
                    season_num = groups[0]
                    episode_num = groups[1]
                else:
                    continue
                return series_title, season_num, episode_num
        return None, None, None

    def organize_media(self):
        try:
            if self.media_type == 'Movies':
                self.organize_movies()
            elif self.media_type == 'TV Shows':
                self.organize_tv_shows()
        except Exception as e:
            self.log_message(f"An error occurred during organization: {e}\n")
            logging.error(f"An error occurred during organization: {e}")
            logging.error(traceback.format_exc())
            self.log_queue.put(('enable_buttons',))

    def organize_movies(self):
        self.log_message("Starting movie organization across selected folders...\n")
        all_movie_files = []
        for source_folder in self.folders:
            for root, _, files in os.walk(source_folder):
                for file in files:
                    if self.is_video_file(file):
                        all_movie_files.append((root, file))

        self.total_files = len(all_movie_files)
        self.update_progress()

        for root, file in all_movie_files:
            try:
                self.process_movie_file(root, file)
            except Exception as e:
                self.log_message(f"Error processing file '{file}': {e}\n")
                logging.error(f"Error processing file '{file}': {e}")
                logging.error(traceback.format_exc())
            self.processed_files += 1
            self.update_progress()

        for source_folder in self.folders:
            self.clean_up_files_and_folders(source_folder)
            self.remove_empty_folders(source_folder)

        self.log_message("Movie organization completed.\n")
        self.confirm_deletion()
        self.delete_files()
        self.log_queue.put(('enable_buttons',))

    def organize_tv_shows(self):
        self.log_message("Starting TV show organization across selected folders...\n")
        all_tv_files = []
        for source_folder in self.folders:
            for root, dirs, files in os.walk(source_folder):
                # Handle season folders without series folders
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    if re.match(r'.*[sS]eason\s*\d+', dir_name):
                        parent_dir = os.path.basename(root)
                        if not re.match(r'.*[sS]eason\s*\d+', parent_dir):
                            # Assume parent_dir is the series title
                            continue
                        else:
                            # Need to create series folder
                            series_title = self.extract_series_title_from_season_folder(dir_name)
                            sanitized_series_title = self.sanitize_filename(series_title)
                            series_folder_path = os.path.join(root, sanitized_series_title)
                            if not os.path.exists(series_folder_path):
                                os.makedirs(series_folder_path, exist_ok=True)
                            shutil.move(dir_path, os.path.join(series_folder_path, dir_name))
                            self.log_message(f"Moved season folder '{dir_path}' to '{series_folder_path}'\n")

            # Collect all video files
            for root, _, files in os.walk(source_folder):
                for file in files:
                    if self.is_video_file(file):
                        all_tv_files.append((root, file))

        self.total_files = len(all_tv_files)
        self.update_progress()

        for root, file in all_tv_files:
            try:
                self.process_tv_show_file(root, file)
            except Exception as e:
                self.log_message(f"Error processing file '{file}': {e}\n")
                logging.error(f"Error processing file '{file}': {e}")
                logging.error(traceback.format_exc())
            self.processed_files += 1
            self.update_progress()

        for source_folder in self.folders:
            self.clean_up_files_and_folders(source_folder)
            self.remove_empty_folders(source_folder)

        self.log_message("TV show organization completed.\n")
        self.confirm_deletion()
        self.delete_files()
        self.log_queue.put(('enable_buttons',))

    def extract_series_title_from_season_folder(self, season_folder_name):
        # Remove 'Season X' from the folder name to get series title
        series_title = re.sub(r'[sS]eason\s*\d+', '', season_folder_name).strip()
        if not series_title:
            series_title = 'Unknown Series'
        return series_title

    def update_progress(self):
        if self.total_files == 0:
            progress = 100
        else:
            progress = int((self.processed_files / self.total_files) * 100)
        self.progress_queue.put(progress)

    def process_movie_file(self, root, file):
        source_file = os.path.join(root, file)
        if not os.path.isfile(source_file):
            return

        if self.is_hidden(source_file):
            return

        filename, ext = os.path.splitext(file)
        title = self.parse_movie_title(filename)
        title = self.capitalize_title(title)
        sanitized_title = self.sanitize_filename(title)
        year = self.get_release_year(source_file)
        if year:
            new_filename = f"{sanitized_title} ({year}){ext}"
            folder_name = f"{sanitized_title} ({year})"
        else:
            new_filename = f"{sanitized_title}{ext}"
            folder_name = sanitized_title

        destination_folder = self.find_movie_destination_folder(source_file, folder_name)
        os.makedirs(destination_folder, exist_ok=True)
        destination_file = os.path.join(destination_folder, new_filename)

        if os.path.normcase(source_file) == os.path.normcase(destination_file):
            return

        if not os.path.exists(destination_file):
            try:
                shutil.move(source_file, destination_file)
                self.log_message(f"Moved '{source_file}' to '{destination_file}'\n")
            except Exception as e:
                self.log_message(f"Error moving file '{source_file}': {e}\n")
                logging.error(f"Error moving file '{source_file}': {e}")
                logging.error(traceback.format_exc())
        else:
            self.handle_duplicate(source_file, destination_file)

    def process_tv_show_file(self, root, file):
        source_file = os.path.join(root, file)
        if not os.path.isfile(source_file):
            return

        if self.is_hidden(source_file):
            return

        filename, ext = os.path.splitext(file)
        series_title, season_num, episode_num = self.parse_tv_show_filename(filename)

        # Use folder names if series title is missing
        if not series_title or series_title.strip() == '':
            series_title = self.capitalize_title(os.path.basename(os.path.dirname(os.path.dirname(source_file))))
            self.log_message(f"Series title inferred from folder: '{series_title}'\n")

        # Use parent folder name for season if season number is missing
        if not season_num:
            season_folder_name = os.path.basename(os.path.dirname(source_file))
            season_match = re.search(r'Season\s*(\d+)', season_folder_name, re.IGNORECASE)
            if season_match:
                season_num = season_match.group(1)
                self.log_message(f"Season number inferred from folder: '{season_num}'\n")
            else:
                season_num = '1'
                self.log_message(f"Season number not found, defaulting to '1'\n")

        # Use MediaInfo to get series title if still missing
        if not series_title or series_title.strip() == '':
            metadata_series_title = self.get_series_name_from_metadata(source_file)
            if metadata_series_title:
                series_title = self.capitalize_title(metadata_series_title)
                self.log_message(f"Series title extracted from metadata: '{series_title}'\n")
            else:
                series_title = 'Unknown Series'
                self.log_message(f"Series title not found, defaulting to 'Unknown Series'\n")

        if not episode_num:
            # Try to extract episode number from filename
            match = re.search(r'[eE](\d+)', filename)
            if match:
                episode_num = match.group(1)
                self.log_message(f"Episode number inferred from filename: '{episode_num}'\n")
            else:
                episode_num = '1'
                self.log_message(f"Episode number not found, defaulting to '1'\n")

        try:
            season_num_int = int(season_num)
            episode_num_int = int(episode_num)
        except ValueError:
            season_num_int = 1
            episode_num_int = 1

        sanitized_series_title = self.sanitize_filename(series_title)
        series_year = self.get_tv_show_release_year(series_title)
        if series_year:
            series_folder_name = f"{sanitized_series_title} ({series_year})"
        else:
            series_folder_name = sanitized_series_title
        season_folder_name = f"Season {season_num_int:02d}"

        new_filename = f"{series_title} S{season_num_int:02d}E{episode_num_int:02d}{ext}"
        destination_folder = self.find_destination_folder(source_file, series_folder_name, season_folder_name)
        os.makedirs(destination_folder, exist_ok=True)
        destination_file = os.path.join(destination_folder, new_filename)

        if os.path.normcase(source_file) == os.path.normcase(destination_file):
            return

        if not os.path.exists(destination_file):
            try:
                shutil.move(source_file, destination_file)
                self.log_message(f"Moved '{source_file}' to '{destination_file}'\n")
            except Exception as e:
                self.log_message(f"Error moving file '{source_file}': {e}\n")
                logging.error(f"Error moving file '{source_file}': {e}")
                logging.error(traceback.format_exc())
        else:
            self.handle_duplicate(source_file, destination_file)

    def find_movie_destination_folder(self, source_file, folder_name):
        source_drive = os.path.splitdrive(source_file)[0]
        for base_folder in self.folders:
            if os.path.splitdrive(base_folder)[0] == source_drive:
                folder_path = os.path.join(base_folder, folder_name)
                if os.path.exists(folder_path):
                    return folder_path
        return os.path.join(os.path.dirname(source_file), folder_name)

    def find_destination_folder(self, source_file, series_folder_name, season_folder):
        source_drive = os.path.splitdrive(source_file)[0]
        for base_folder in self.folders:
            if os.path.splitdrive(base_folder)[0] == source_drive:
                series_folder_path = os.path.join(base_folder, series_folder_name)
                if not os.path.exists(series_folder_path):
                    os.makedirs(series_folder_path, exist_ok=True)
                return os.path.join(series_folder_path, season_folder)
        return os.path.join(os.path.dirname(source_file), series_folder_name, season_folder)

    def get_tv_show_season_year(self, series_title, season_number):
        try:
            url = f"https://api.tvmaze.com/singlesearch/shows"
            params = {'q': series_title, 'embed': 'seasons'}
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                seasons = data.get('_embedded', {}).get('seasons', [])
                for season in seasons:
                    if season['number'] == season_number:
                        premiere_date = season.get('premiereDate')
                        if premiere_date:
                            year = premiere_date.split('-')[0]
                            return year
            else:
                self.log_message(f"Failed to fetch season year for '{series_title} Season {season_number}'. Status code: {response.status_code}\n")
        except Exception as e:
            self.log_message(f"Error fetching season year for '{series_title} Season {season_number}': {e}\n")
            logging.error(f"Error fetching season year for '{series_title} Season {season_number}': {e}")
            logging.error(traceback.format_exc())
        return None

    def clean_up_files_and_folders(self, path):
        for root, dirs, files in os.walk(path, topdown=False):
            # Delete unwanted files
            for file in files:
                file_path = os.path.join(root, file)
                if not self.is_video_file(file) and not self.is_subtitle_file(file):
                    try:
                        os.remove(file_path)
                        self.log_message(f"Deleted unwanted file '{file_path}'\n")
                    except Exception as e:
                        self.log_message(f"Error deleting file '{file_path}': {e}\n")
                        logging.error(f"Error deleting file '{file_path}': {e}")
                        logging.error(traceback.format_exc())

    def remove_empty_folders(self, path):
        if not os.path.isdir(path):
            return

        files = os.listdir(path)
        if len(files):
            for f in files:
                fullpath = os.path.join(path, f)
                if os.path.isdir(fullpath):
                    self.remove_empty_folders(fullpath)

        files = os.listdir(path)
        if len(files) == 0:
            try:
                os.rmdir(path)
                self.log_message(f"Removed empty folder '{path}'\n")
            except Exception as e:
                self.log_message(f"Error removing folder '{path}': {e}\n")
                logging.error(f"Error removing folder '{path}': {e}")
                logging.error(traceback.format_exc())

    def confirm_deletion(self):
        if not self.files_to_delete:
            self.log_queue.put(('enable_buttons',))
            return

        self.log_queue.put(('confirm_deletion', self.files_to_delete))

    def delete_files(self):
        for file in self.files_to_delete:
            try:
                os.remove(file)
                self.log_message(f"Deleted duplicate file '{file}'\n")
            except Exception as e:
                self.log_message(f"Error deleting file '{file}': {e}\n")
                logging.error(f"Error deleting file '{file}': {e}")
                logging.error(traceback.format_exc())

    def handle_duplicate(self, source_file, destination_file):
        try:
            source_size = os.path.getsize(source_file)
            dest_size = os.path.getsize(destination_file)
            if source_size != dest_size:
                self.rename_and_move_duplicate(source_file, destination_file)
                return
            source_hash = self.compute_file_hash(source_file, first_chunk_only=True, chunk_size=1024 * 1024)
            dest_hash = self.compute_file_hash(destination_file, first_chunk_only=True, chunk_size=1024 * 1024)
            if source_hash != dest_hash:
                self.rename_and_move_duplicate(source_file, destination_file)
                return
            source_full_hash = self.compute_file_hash(source_file)
            dest_full_hash = self.compute_file_hash(destination_file)
            if source_full_hash == dest_full_hash:
                source_drive = os.path.splitdrive(source_file)[0]
                dest_drive = os.path.splitdrive(destination_file)[0]
                source_free_space = self.get_drive_free_space(source_drive)
                dest_free_space = self.get_drive_free_space(dest_drive)
                if source_free_space < dest_free_space:
                    self.files_to_delete.append(source_file)
                    self.log_message(f"Marked for deletion (less free space): '{source_file}'\n")
                else:
                    self.files_to_delete.append(destination_file)
                    self.log_message(f"Marked for deletion (less free space): '{destination_file}'\n")
            else:
                self.rename_and_move_duplicate(source_file, destination_file)
        except Exception as e:
            self.log_message(f"Error handling duplicate file '{source_file}': {e}\n")
            logging.error(f"Error handling duplicate file '{source_file}': {e}")
            logging.error(traceback.format_exc())

    def compute_file_hash(self, file_path, first_chunk_only=False, chunk_size=4096):
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                if first_chunk_only:
                    chunk = f.read(chunk_size)
                    hash_md5.update(chunk)
                else:
                    for chunk in iter(lambda: f.read(chunk_size), b""):
                        hash_md5.update(chunk)
        except Exception as e:
            self.log_message(f"Error computing hash for file '{file_path}': {e}\n")
            logging.error(f"Error computing hash for file '{file_path}': {e}")
            logging.error(traceback.format_exc())
            return None
        return hash_md5.hexdigest()

    def rename_and_move_duplicate(self, source_file, destination_file):
        filename, ext = os.path.splitext(os.path.basename(source_file))
        new_filename = f"{filename}_copy{ext}"
        new_destination = os.path.join(os.path.dirname(destination_file), new_filename)
        counter = 1
        while os.path.exists(new_destination):
            new_filename = f"{filename}_copy{counter}{ext}"
            new_destination = os.path.join(os.path.dirname(destination_file), new_filename)
            counter += 1
        try:
            shutil.move(source_file, new_destination)
            self.log_message(f"Moved '{source_file}' to '{new_destination}' (duplicate with different content)\n")
        except Exception as e:
            self.log_message(f"Error moving duplicate file '{source_file}': {e}\n")
            logging.error(f"Error moving duplicate file '{source_file}': {e}")
            logging.error(traceback.format_exc())

    def get_drive_free_space(self, drive):
        if sys.platform == 'win32':
            drive_path = drive + '\\'
        else:
            drive_path = drive
        try:
            total, used, free = shutil.disk_usage(drive_path)
            return free
        except Exception as e:
            self.log_message(f"Error getting free space for drive '{drive}': {e}\n")
            logging.error(f"Error getting free space for drive '{drive}': {e}")
            logging.error(traceback.format_exc())
            return 0

    # Sonarr integration methods
    def analyze_missing_episodes(self):
        self.log_message("Starting missing episodes analysis...\n")
        missing_episodes = {}
        for source_folder in self.folders:
            for series_folder in os.listdir(source_folder):
                series_path = os.path.join(source_folder, series_folder)
                if os.path.isdir(series_path):
                    series_title = re.sub(r'\s\(\d{4}\)$', '', series_folder)
                    series_id = self.get_series_id(series_title)
                    if not series_id:
                        self.log_message(f"Series '{series_title}' not found in Sonarr.\n")
                        continue
                    episodes = self.get_series_episodes(series_id)
                    if not episodes:
                        self.log_message(f"No episodes found for series '{series_title}' in Sonarr.\n")
                        continue
                    existing_episodes = self.get_existing_episodes(series_path)
                    missing = [ep for ep in episodes if ep not in existing_episodes]
                    if missing:
                        missing_episodes[series_title] = missing
        # Display missing episodes and prompt for selection
        self.log_queue.put(('prompt_missing_episodes', missing_episodes))
        self.log_message("Missing episodes analysis completed.\n")

    def get_series_id(self, series_title):
        if not self.sonarr_api_key:
            self.log_message("Sonarr API key not set. Cannot fetch series ID.\n")
            return None
        try:
            url = f"{self.sonarr_url}/series"
            params = {'apikey': self.sonarr_api_key}
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                for series in data:
                    if series['title'].lower() == series_title.lower():
                        return series['id']
            else:
                self.log_message(f"Failed to fetch series list from Sonarr. Status code: {response.status_code}\n")
        except Exception as e:
            self.log_message(f"Error fetching series ID for '{series_title}': {e}\n")
            logging.error(f"Error fetching series ID for '{series_title}': {e}")
            logging.error(traceback.format_exc())
        return None

    def get_series_episodes(self, series_id):
        if not self.sonarr_api_key:
            self.log_message("Sonarr API key not set. Cannot fetch series episodes.\n")
            return []
        try:
            url = f"{self.sonarr_url}/episode"
            params = {'seriesId': series_id, 'apikey': self.sonarr_api_key}
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                episodes = []
                for ep in data:
                    episodes.append((ep['seasonNumber'], ep['episodeNumber']))
                return episodes
            else:
                self.log_message(f"Failed to fetch episodes for series ID '{series_id}'. Status code: {response.status_code}\n")
        except Exception as e:
            self.log_message(f"Error fetching episodes for series ID '{series_id}': {e}\n")
            logging.error(f"Error fetching episodes for series ID '{series_id}': {e}")
            logging.error(traceback.format_exc())
        return []

    def get_existing_episodes(self, series_path):
        existing_episodes = []
        for season_folder in os.listdir(series_path):
            season_path = os.path.join(series_path, season_folder)
            if os.path.isdir(season_path):
                season_match = re.search(r'Season (\d+)', season_folder, re.IGNORECASE)
                if season_match:
                    season_number = int(season_match.group(1))
                    for file in os.listdir(season_path):
                        filename, ext = os.path.splitext(file)
                        if self.is_video_file(file):
                            episode_match = re.search(r'E(\d+)', filename, re.IGNORECASE)
                            if episode_match:
                                episode_number = int(episode_match.group(1))
                                existing_episodes.append((season_number, episode_number))
        return existing_episodes

    def add_missing_episodes_to_sonarr(self, series_title, episodes):
        # Implement the logic to add missing episodes to Sonarr
        pass

def main():
    root = tk.Tk()
    root.title("Media Organizer")
    root.geometry("800x600")
    root.configure(bg='#2e2e2e')  # Set dark background

    # Read config.ini
    import sys
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(__file__)

    config_path = os.path.join(application_path, 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path)

    log_queue = queue.Queue()
    progress_queue = queue.Queue()
    organizer = None

    style = ttk.Style()
    style.theme_use('default')
    style.configure('.', background='#2e2e2e', foreground='#ffffff', fieldbackground='#2e2e2e')
    style.configure('TLabel', background='#2e2e2e', foreground='#ffffff')
    style.configure('TButton', background='#3e3e3e', foreground='#ffffff', borderwidth=0)
    style.map('TButton', background=[('active', '#4e4e4e')])

    # Remove focus rectangle from buttons
    style.layout('NoFocus.TButton', [
        ('Button.border', {'sticky': 'nswe', 'children': [
            ('Button.padding', {'sticky': 'nswe', 'children': [
                ('Button.label', {'sticky': 'nswe'})
            ]})
        ]})
    ])

    # Media Type Selection
    media_type_label = tk.Label(root, text="Select Media Type:", bg='#2e2e2e', fg='#ffffff')
    media_type_label.pack(pady=5)
    media_type_var = tk.StringVar(value='Movies')
    media_type_options = ['Movies', 'TV Shows']
    media_type_menu = ttk.Combobox(root, textvariable=media_type_var, values=media_type_options, state='readonly')
    media_type_menu.pack()

    # Folder Selection
    folder_paths = []

    def select_folders():
        folder_selected = filedialog.askdirectory()
        if folder_selected and folder_selected not in folder_paths:
            folder_paths.append(folder_selected)
            folder_list.insert(tk.END, folder_selected)
        elif folder_selected in folder_paths:
            messagebox.showinfo("Folder Already Selected", "This folder has already been selected.")

    select_folders_button = ttk.Button(root, text="Select Folders", command=select_folders, style='NoFocus.TButton')
    select_folders_button.pack(pady=5)

    # Folder Listbox with scrollbar
    folder_frame = tk.Frame(root, bg='#2e2e2e')
    folder_frame.pack()

    folder_scrollbar = tk.Scrollbar(folder_frame, orient=tk.VERTICAL)
    folder_list = tk.Listbox(folder_frame, width=80, height=6, yscrollcommand=folder_scrollbar.set, bg='#3e3e3e', fg='#ffffff', highlightthickness=0, selectbackground='#5e5e5e')
    folder_scrollbar.config(command=folder_list.yview)
    folder_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    folder_list.pack(side=tk.LEFT, fill=tk.BOTH)

    def remove_selected_folder():
        selected_indices = folder_list.curselection()
        for index in reversed(selected_indices):
            folder_path = folder_list.get(index)
            folder_paths.remove(folder_path)
            folder_list.delete(index)

    remove_folder_button = ttk.Button(root, text="Remove Selected Folder", command=remove_selected_folder, style='NoFocus.TButton')
    remove_folder_button.pack(pady=5)

    # Control Buttons Frame
    control_frame = ttk.Frame(root)
    control_frame.pack(pady=5)

    # Progress Bar
    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(root, orient='horizontal', length=400, mode='determinate', variable=progress_var)
    progress_bar.pack(pady=5)

    # Start Button
    def start_organizing():
        nonlocal organizer
        if not folder_paths:
            messagebox.showerror("Error", "Please select at least one folder to organize.")
            return

        start_button.config(state='disabled')
        missing_episodes_button.config(state='disabled')

        organizer = MediaOrganizer(log_queue, media_type_var.get(), folder_paths, progress_queue, config)

        threading.Thread(target=organize_media, args=(organizer,), daemon=True).start()

        check_log_queue()
        update_progress_bar()

    start_button = ttk.Button(control_frame, text="Start Organizing", command=start_organizing, style='NoFocus.TButton')
    start_button.pack(side=tk.LEFT, padx=10)

    # Missing Episodes Button
    def analyze_missing_episodes():
        nonlocal organizer
        if not folder_paths:
            messagebox.showerror("Error", "Please select at least one folder to analyze.")
            return

        start_button.config(state='disabled')
        missing_episodes_button.config(state='disabled')

        organizer = MediaOrganizer(log_queue, 'TV Shows', folder_paths, progress_queue, config)

        threading.Thread(target=analyze_episodes, args=(organizer,), daemon=True).start()

        check_log_queue()
        update_progress_bar()

    missing_episodes_button = ttk.Button(control_frame, text="Missing Episodes", command=analyze_missing_episodes, style='NoFocus.TButton')
    missing_episodes_button.pack(side=tk.LEFT, padx=10)

    # Log Text Widget with black background and green text
    log_text = scrolledtext.ScrolledText(root, state='disabled', wrap=tk.WORD, bg='#1e1e1e', fg='#00ff00')
    log_text.pack(pady=10, fill=tk.BOTH, expand=True)

    def check_log_queue():
        try:
            while True:
                item = log_queue.get_nowait()
                if isinstance(item, tuple):
                    if item[0] == 'confirm_deletion':
                        duplicates = item[1]
                        confirm_deletion(duplicates)
                    elif item[0] == 'enable_buttons':
                        start_button.config(state='normal')
                        missing_episodes_button.config(state='normal')
                    elif item[0] == 'prompt_missing_episodes':
                        selection_data = item[1]
                        prompt_missing_episodes(selection_data)
                else:
                    log_text.configure(state='normal')
                    log_text.insert(tk.END, item)
                    log_text.configure(state='disabled')
                    log_text.see(tk.END)
        except queue.Empty:
            pass
        root.after(100, check_log_queue)

    def update_progress_bar():
        try:
            while True:
                progress = progress_queue.get_nowait()
                progress_var.set(progress)
        except queue.Empty:
            pass
        root.after(100, update_progress_bar)

    def confirm_deletion(files_to_delete):
        if not files_to_delete:
            start_button.config(state='normal')
            missing_episodes_button.config(state='normal')
            return

        confirm_window = tk.Toplevel()
        confirm_window.title("Confirm Deletion")
        confirm_window.geometry("600x400")
        confirm_window.configure(bg='#2e2e2e')

        lbl = tk.Label(confirm_window, text="The following duplicate files have been found. Select the ones you want to delete:", bg='#2e2e2e', fg='#ffffff')
        lbl.pack(pady=5)

        var_list = []
        listbox = tk.Listbox(confirm_window, selectmode=tk.MULTIPLE, width=80, bg='#3e3e3e', fg='#ffffff', highlightthickness=0, selectbackground='#5e5e5e')
        for file in files_to_delete:
            listbox.insert(tk.END, file)
        listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        def confirm():
            selected_indices = listbox.curselection()
            selected_files = [files_to_delete[i] for i in selected_indices]
            organizer.files_to_delete = selected_files
            confirm_window.destroy()
            organizer.delete_files()
            start_button.config(state='normal')
            missing_episodes_button.config(state='normal')

        confirm_button = ttk.Button(confirm_window, text="Delete Selected Files", command=confirm, style='NoFocus.TButton')
        confirm_button.pack(pady=5)

    def prompt_missing_episodes(missing_episodes):
        if not missing_episodes:
            start_button.config(state='normal')
            missing_episodes_button.config(state='normal')
            messagebox.showinfo("No Missing Episodes", "No missing episodes were found.")
            return

        missing_window = tk.Toplevel()
        missing_window.title("Missing Episodes")
        missing_window.geometry("600x400")
        missing_window.configure(bg='#2e2e2e')

        lbl = tk.Label(missing_window, text="Select missing episodes to add to Sonarr:", bg='#2e2e2e', fg='#ffffff')
        lbl.pack(pady=5)

        episodes_list = tk.Listbox(missing_window, selectmode=tk.MULTIPLE, width=80, bg='#3e3e3e', fg='#ffffff', highlightthickness=0, selectbackground='#5e5e5e')
        episode_items = []
        for series_title, episodes in missing_episodes.items():
            for ep in episodes:
                item = f"{series_title} - S{ep[0]:02d}E{ep[1]:02d}"
                episode_items.append((series_title, ep))
                episodes_list.insert(tk.END, item)
        episodes_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        def add_episodes():
            selected_indices = episodes_list.curselection()
            selected_episodes = [episode_items[i] for i in selected_indices]
            for series_title, ep in selected_episodes:
                organizer.add_missing_episodes_to_sonarr(series_title, [ep])
            missing_window.destroy()
            start_button.config(state='normal')
            missing_episodes_button.config(state='normal')
            messagebox.showinfo("Episodes Added", "Selected episodes have been added to Sonarr.")

        add_button = ttk.Button(missing_window, text="Add Selected Episodes", command=add_episodes, style='NoFocus.TButton')
        add_button.pack(pady=5)

    def organize_media(organizer_instance):
        try:
            organizer_instance.organize_media()
            organizer_instance.log_message("Organization process completed successfully.\n")
        except Exception as e:
            organizer_instance.log_message(f"An error occurred: {e}\n")
            logging.error(f"An error occurred: {e}")
            logging.error(traceback.format_exc())
            start_button.config(state='normal')
            missing_episodes_button.config(state='normal')

    def analyze_episodes(organizer_instance):
        try:
            organizer_instance.analyze_missing_episodes()
        except Exception as e:
            organizer_instance.log_message(f"An error occurred during analysis: {e}\n")
            logging.error(f"An error occurred during analysis: {e}")
            logging.error(traceback.format_exc())
            start_button.config(state='normal')
            missing_episodes_button.config(state='normal')

    root.mainloop()

if __name__ == "__main__":
    main()
