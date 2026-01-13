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

    if not os.path.isdir(target_dir):
        print(f"❌ Error: The directory '{target_dir}' does not exist.")
        return

    # Define paths
    temp_dir = os.path.join(target_dir, "temp_clips")
    list_file_path = os.path.join(target_dir, "ffmpeg_list.txt")
    output_video = os.path.join(target_dir, "Final_Highlights.mp4")

    try:
        # 1. Find all JSON files
        search_pattern = os.path.join(target_dir, "*.json")
        json_files = sorted(glob.glob(search_pattern))
        
        if not json_files:
            print(f"❌ No JSON files found in directory: {target_dir}")
            return

        print(f"📂 Found {len(json_files)} JSON file(s).")

        all_segments = []

        # 2. Parse all JSON files
        for j_file in json_files:
            try:
                with open(j_file, 'r') as f:
                    data = json.load(f)
                    
                    # Detect mode (default to youtube if missing)
                    mode = data.get('mode', 'youtube')
                    video_id = data.get('videoId')
                    video_filename = data.get('videoPath')
                    video_title = data.get('videoTitle', 'unknown')
                    
                    for seg in data.get('segments', []):
                        all_segments.append({
                            'mode': mode,
                            'video_id': video_id,
                            'video_filename': video_filename,
                            'video_title': video_title,
                            'start': seg['start'],
                            'end': seg['end']
                        })
            except Exception as e:
                print(f"   ⚠️ Skipping invalid file {os.path.basename(j_file)}: {e}")

        if not all_segments:
            print("❌ No valid segments found.")
            return

        print(f"🎬 Found {len(all_segments)} total segments to process.")

        # 3. Create temp directory
        os.makedirs(temp_dir, exist_ok=True)
        downloaded_clips = []

        print("\n⬇️  Processing Segments...")

        # 4. Processing Loop
        for i, seg in enumerate(all_segments):
            
            output_filename = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
            
            # --- PATH A: YOUTUBE ---
            if seg['mode'] == 'youtube':
                print(f"   [{i+1}/{len(all_segments)}] Downloading (YT): {seg['video_title']}")
                
                url = f"https://www.youtube.com/watch?v={seg['video_id']}"
                
                ydl_opts = {
                    'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'quiet': True,
                    'no_warnings': True,
                    'download_ranges': lambda info, ydl: [{'start_time': seg['start'], 'end_time': seg['end']}], 
                    'force_keyframes_at_cuts': True,
                    'outtmpl': output_filename,
                }
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    
                    # yt-dlp might tweak the extension or name, find the match
                    matches = glob.glob(os.path.join(temp_dir, f"clip_{i:03d}*"))
                    if matches:
                        downloaded_clips.append(matches[0])
                    else:
                        print(f"   ⚠️ Error: Download failed for segment {i}")
                except Exception as e:
                    print(f"   ❌ YouTube Error: {e}")

            # --- PATH B: LOCAL FILE ---
            elif seg['mode'] == 'local':
                source_file = os.path.join(target_dir, seg['video_filename'])
                print(f"   [{i+1}/{len(all_segments)}] Extracting (Local): {seg['video_filename']} ({format_time(seg['start'])} - {format_time(seg['end'])})")
                
                if not os.path.exists(source_file):
                    print(f"      ❌ ERROR: Source file not found: {source_file}")
                    print("      (Make sure the video file is in the same folder as this script)")
                    continue

                # Use FFmpeg to slice local file
                # -ss = start, -to = end (faster and accurate if before -i)
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(seg['start']),
                    "-to", str(seg['end']),
                    "-i", source_file,
                    "-c:v", "libx264", "-c:a", "aac", # Re-encode to ensure uniform format for concatenation
                    "-preset", "fast",
                    "-avoid_negative_ts", "make_zero",
                    output_filename
                ]

                try:
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    downloaded_clips.append(output_filename)
                except subprocess.CalledProcessError as e:
                    print(f"      ❌ FFmpeg Error: {e}")

        # 5. Concatenate Clips
        if len(downloaded_clips) > 0:
            print("\nEditing final video...")
            
            with open(list_file_path, 'w') as f:
                for clip in downloaded_clips:
                    abs_path = os.path.abspath(clip).replace("'", "'\\''")
                    f.write(f"file '{abs_path}'\n")

            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file_path,
                "-c", "copy", "-y", output_video
            ]
            
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"\n✅ Success! Video saved as: {output_video}")
            except Exception as e:
                print(f"\n❌ Merge Error: {e}")
        else:
            print("❌ No clips were successfully generated.")

    except Exception as main_e:
        print(f"\n❌ A Critical Error Occurred: {main_e}")

    finally:
        # Cleanup
        print("\n🧹 Cleaning up temporary files...")
        if os.path.exists(list_file_path):
            try: os.remove(list_file_path)
            except: pass
        if os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir)
            except: pass
        print("✨ Done.")

def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

if __name__ == "__main__":
    main()