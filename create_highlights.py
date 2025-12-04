import json
import os
import sys
import glob
import subprocess
import shutil
import yt_dlp

def main():
    # 0. Check for command line argument for folder path
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = "." # Default to current directory

    # Verify directory exists
    if not os.path.isdir(target_dir):
        print(f"❌ Error: The directory '{target_dir}' does not exist.")
        return

    # Define paths
    temp_dir = os.path.join(target_dir, "temp_clips")
    list_file_path = os.path.join(target_dir, "ffmpeg_list.txt")
    output_video = os.path.join(target_dir, "Final_Highlights.mp4")

    try:
        # 1. Find all JSON files in the target directory
        # We use sorted() to ensure videos are processed in alphanumeric order 
        search_pattern = os.path.join(target_dir, "*.json")
        json_files = sorted(glob.glob(search_pattern))
        
        if not json_files:
            print(f"❌ No JSON files found in directory: {target_dir}")
            return

        print(f"📂 Found {len(json_files)} JSON file(s) in '{target_dir}':")
        for f in json_files:
            print(f"   - {os.path.basename(f)}")

        all_segments = []

        # 2. Parse all JSON files
        for j_file in json_files:
            try:
                with open(j_file, 'r') as f:
                    data = json.load(f)
                    video_id = data.get('videoId')
                    video_title = data.get('videoTitle', 'unknown_video')
                    
                    for seg in data.get('segments', []):
                        all_segments.append({
                            'video_id': video_id,
                            'video_title': video_title,
                            'start': seg['start'],
                            'end': seg['end'],
                            'duration': seg['end'] - seg['start']
                        })
            except Exception as e:
                print(f"   ⚠️ Skipping invalid file {os.path.basename(j_file)}: {e}")

        if not all_segments:
            print("❌ No valid segments found inside the JSON files.")
            return

        print(f"🎬 Found {len(all_segments)} total segments to process.")

        # 3. Create temp directory
        os.makedirs(temp_dir, exist_ok=True)

        downloaded_clips = []

        # 4. Configure yt-dlp
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'download_ranges': None, 
            'force_keyframes_at_cuts': True,
            'outtmpl': os.path.join(temp_dir, 'clip_%(autonumber)03d.%(ext)s'),
        }

        print("\n⬇️  Starting Downloads (Only downloading specific segments)...")

        # 5. Download Loop
        for i, seg in enumerate(all_segments):
            url = f"https://www.youtube.com/watch?v={seg['video_id']}"
            start_time = seg['start']
            end_time = seg['end']
            
            # Create a unique filename for this segment
            output_filename = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
            
            current_opts = ydl_opts.copy()
            
            def download_range_func(info_dict, ydl):
                return [{
                    'start_time': start_time,
                    'end_time': end_time,
                    'title': f"Segment {i}"
                }]

            current_opts['download_ranges'] = download_range_func
            current_opts['outtmpl'] = output_filename

            print(f"   [{i+1}/{len(all_segments)}] Downloading: {seg['video_title']} ({format_time(start_time)} - {format_time(end_time)})")

            try:
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    ydl.download([url])
                
                # Verify file existence (yt-dlp might append .mp4 or merge formats)
                # We look for the base file we expected
                found_files = glob.glob(os.path.join(temp_dir, f"clip_{i:03d}*"))
                if found_files:
                    downloaded_clips.append(found_files[0])
                else:
                    print(f"   ⚠️ Warning: File for segment {i} not found.")

            except Exception as e:
                print(f"   ❌ Error downloading segment {i}: {e}")

        # 6. Concatenate Clips
        if len(downloaded_clips) > 0:
            print("\nEditing final video...")
            
            with open(list_file_path, 'w') as f:
                for clip in downloaded_clips:
                    # Convert to absolute path to avoid ffmpeg relative path issues
                    abs_path = os.path.abspath(clip)
                    # Escape absolute paths for FFmpeg
                    safe_path = abs_path.replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")

            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file_path,
                "-c", "copy", "-y", output_video
            ]
            
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"\n✅ Success! Video saved as: {output_video}")
                
            except subprocess.CalledProcessError:
                print("\n❌ FFmpeg Merge Error. Trying re-encode fallback...")
                cmd_reencode = [
                    "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file_path,
                    "-c:v", "libx264", "-c:a", "aac", "-y", output_video
                ]
                subprocess.run(cmd_reencode, check=True)
                print(f"\n✅ Success (Re-encoded)! Video saved as: {output_video}")

        else:
            print("❌ No clips were successfully downloaded.")

    except Exception as main_e:
        print(f"\n❌ A Critical Error Occurred: {main_e}")

    finally:
        # --- CLEANUP SECTION ---
        print("\n🧹 Cleaning up temporary files...")
        
        # Remove the text list file
        if os.path.exists(list_file_path):
            try:
                os.remove(list_file_path)
            except OSError:
                pass

        # Remove the temp directory and all downloaded clips
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except OSError as e:
                print(f"   ⚠️ Could not remove temp folder: {e}")
        
        print("✨ Done.")

def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

if __name__ == "__main__":
    main()