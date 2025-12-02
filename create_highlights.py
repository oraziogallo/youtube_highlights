import json
import os
import sys
import glob
import subprocess
import yt_dlp

def main():
    # 1. Find all JSON files in the current directory (or passed as args)
    json_files = glob.glob("*.json")
    
    if not json_files:
        print("❌ No JSON files found in the current directory.")
        print("   Please export the JSON from the web tool and save it here.")
        return

    print(f"📂 Found {len(json_files)} JSON file(s): {', '.join(json_files)}")

    all_segments = []

    # 2. Parse all JSON files and gather segments
    for j_file in json_files:
        with open(j_file, 'r') as f:
            data = json.load(f)
            video_id = data.get('videoId')
            video_title = data.get('videoTitle', 'unknown_video')
            
            # Add video info to each segment so we know where it comes from
            for seg in data.get('segments', []):
                all_segments.append({
                    'video_id': video_id,
                    'video_title': video_title,
                    'start': seg['start'],
                    'end': seg['end'],
                    'duration': seg['end'] - seg['start']
                })

    if not all_segments:
        print("❌ No segments found inside the JSON files.")
        return

    print(f"🎬 Found {len(all_segments)} total segments to process.")

    # 3. Create a temporary folder for clips
    temp_dir = "temp_clips"
    os.makedirs(temp_dir, exist_ok=True)

    downloaded_clips = []

    # 4. Download Loop
    # We force 1080p mp4 to ensure all clips have compatible resolution/codecs for merging
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        # This is the magic setting: Download ONLY the specific range
        'download_ranges': None, 
        'force_keyframes_at_cuts': True, # Re-encodes at cut points for precision
        'outtmpl': f'{temp_dir}/clip_%(autonumber)03d.%(ext)s',
    }

    print("\n⬇️  Starting Downloads (Only downloading specific segments)...")

    # We iterate and download one by one to keep order and ensure unique filenames
    for i, seg in enumerate(all_segments):
        url = f"https://www.youtube.com/watch?v={seg['video_id']}"
        start_time = seg['start']
        end_time = seg['end']
        
        output_filename = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
        
        # We must configure a fresh yt_dlp instance for each segment range
        # because the library isn't designed to change ranges on the fly easily
        current_opts = ydl_opts.copy()
        
        # The syntax for yt-dlp download sections is a callback or specific range function
        # easier method via Python wrapper: use the 'download_ranges' callback
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
            
            # Check if file exists (yt-dlp might append .mp4 automatically)
            # Sometimes yt-dlp output differs slightly, we need to find what it made
            found_files = glob.glob(os.path.join(temp_dir, f"clip_{i:03d}*"))
            if found_files:
                downloaded_clips.append(found_files[0])
            else:
                print(f"   ⚠️ Warning: File for segment {i} not found.")

        except Exception as e:
            print(f"   ❌ Error downloading segment {i}: {e}")

    # 5. Concatenate Clips using FFmpeg
    if len(downloaded_clips) > 0:
        print("\nEditing final video...")
        
        # Create a text file list for ffmpeg
        list_file_path = "ffmpeg_list.txt"
        with open(list_file_path, 'w') as f:
            for clip in downloaded_clips:
                # FFMPEG requires absolute paths or relative safe paths
                # escape single quotes
                safe_path = clip.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        output_video = "Final_Highlights.mp4"
        
        # Run FFmpeg Concat
        # -safe 0: Allow unsafe file paths
        # -c copy: Smart rendering (no re-encoding) - super fast
        # Note: If videos have drastically different resolutions, remove '-c copy' to force re-encode
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file_path,
            "-c", "copy", 
            "-y", # Overwrite output
            output_video
        ]
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"\n✅ Success! Video saved as: {output_video}")
            
            # Optional: Cleanup
            # for clip in downloaded_clips:
            #    os.remove(clip)
            # os.remove(list_file_path)
            # os.rmdir(temp_dir)
            
        except subprocess.CalledProcessError:
            print("\n❌ FFmpeg Error. This usually happens if the input videos have different resolutions.")
            print("   Trying again with re-encoding (slower but safer)...")
            
            # Fallback command: Re-encode video stream, copy audio
            cmd_reencode = [
                "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file_path,
                "-c:v", "libx264", "-c:a", "aac", "-y", output_video
            ]
            subprocess.run(cmd_reencode, check=True)
            print(f"\n✅ Success (Re-encoded)! Video saved as: {output_video}")

    else:
        print("❌ No clips were successfully downloaded.")

def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

if __name__ == "__main__":
    main()