import json
import os
import sys
import glob
import subprocess
import shutil
import yt_dlp
import platform

def get_font_path():
    """Attempts to find a usable font path based on OS."""
    system = platform.system()
    if system == "Windows":
        return "C\\\\:/Windows/Fonts/arial.ttf" # Double escaped for FFmpeg
    elif system == "Darwin": # MacOS
        return "/System/Library/Fonts/Helvetica.ttc"
    else: # Linux
        return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def get_video_dimensions(filepath):
    """
    Probes the video file to get width and height. 
    Returns (width, height) or (1920, 1080) as fallback.
    """
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", filepath
        ]
        # Run ffprobe
        output = subprocess.check_output(cmd).decode("utf-8").strip()
        if not output:
            return 1920, 1080
        w, h = map(int, output.split('x'))
        return w, h
    except Exception as e:
        print(f"       ⚠️ Warning: Could not detect resolution ({e}). Defaulting to 1920x1080.")
        return 1920, 1080

def main():
    # Parse Arguments (Handle -p flag and target path)
    args = sys.argv[1:]
    show_progression = False
    if '-p' in args:
        show_progression = True
        args.remove('-p')
    
    target_arg = args[0] if args else "."
    
    json_file = None
    work_dir = "."

    # Check if argument is a specific JSON file
    if os.path.isfile(target_arg) and target_arg.lower().endswith('.json'):
        json_file = target_arg
        work_dir = os.path.dirname(target_arg) or "."
    # Check if argument is a directory
    elif os.path.isdir(target_arg):
        work_dir = target_arg
        files = glob.glob(os.path.join(work_dir, "*.json"))
        if len(files) == 1:
            json_file = files[0]
        elif len(files) > 1:
            print(f"❌ Error: Multiple JSON files found in '{work_dir}'. Please specify the exact file.")
            print("Usage: python create_scored_video.py [-p] path/to/game.json")
            return
        else:
            print(f"❌ Error: No JSON files found in '{work_dir}'.")
            return
    else:
        print(f"❌ Error: Input '{target_arg}' not found.")
        return

    print(f"📂 Processing File: {os.path.basename(json_file)}")

    # Paths
    temp_dir = os.path.join(work_dir, "temp_clips")
    processed_dir = os.path.join(work_dir, "processed_clips")
    list_file_path = os.path.join(work_dir, "ffmpeg_list.txt")
    
    # Generate output filename based on JSON name (e.g., "my_game.json" -> "my_game_Highlights.mp4")
    base_name = os.path.splitext(os.path.basename(json_file))[0]
    output_video = os.path.join(work_dir, f"{base_name}_Highlights.mp4")

    try:
        all_segments = []
        
        # Parse JSON and collect Team Names + Segments
        with open(json_file, 'r') as f:
            data = json.load(f)
            video_id = data.get('videoId')
            t1_name = data.get('team1', 'Home')
            t2_name = data.get('team2', 'Away')
            
            segments = data.get('segments', [])
            
            # Pre-calculate winners if progression is enabled
            prev_s1 = 0
            prev_s2 = 0
            
            for seg in segments:
                score = seg.get('scoreState', {'t1':0, 't2':0})
                
                winner = 0
                if score['t1'] > prev_s1:
                    winner = 1
                    prev_s1 = score['t1']
                elif score['t2'] > prev_s2:
                    winner = 2
                    prev_s2 = score['t2']

                # Sanitize names for FFmpeg (escape colons and remove quotes)
                t1_clean = t1_name.replace(":", "\\:").replace("'", "")
                t2_clean = t2_name.replace(":", "\\:").replace("'", "")
                
                all_segments.append({
                    'video_id': video_id,
                    'start': seg['start'],
                    'end': seg['end'],
                    't1_name': t1_clean,
                    't2_name': t2_clean,
                    's1': score['t1'],
                    's2': score['t2'],
                    'winner': winner
                })

        if not all_segments:
            print("❌ No valid segments found in the JSON file.")
            return

        print(f"🎬 Found {len(all_segments)} segments. Starting processing...")
        if show_progression:
            print("📊 Progression visualization enabled.")

        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(processed_dir, exist_ok=True)

        downloaded_clips = []
        font_path = get_font_path()

        # --- PHASE 1: DOWNLOAD & PROCESS ---
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'force_keyframes_at_cuts': True,
            'download_ranges': None, # Set dynamically
            'outtmpl': os.path.join(temp_dir, 'raw_%(autonumber)03d.%(ext)s'),
        }

        total_segs = len(all_segments)

        for i, seg in enumerate(all_segments):
            url = f"https://www.youtube.com/watch?v={seg['video_id']}"
            raw_filename = os.path.join(temp_dir, f"raw_{i:03d}.mp4")
            final_filename = os.path.join(processed_dir, f"clip_{i:03d}.mp4")
            
            # Skip if already exists (resume capability)
            if os.path.exists(final_filename):
                print(f"   [{i+1}/{total_segs}] Skipping (already processed).")
                downloaded_clips.append(final_filename)
                continue

            # 1. Download raw clip
            print(f"   [{i+1}/{total_segs}] Downloading...")
            
            current_opts = ydl_opts.copy()
            def download_range_func(info_dict, ydl):
                return [{'start_time': seg['start'], 'end_time': seg['end']}]
            current_opts['download_ranges'] = download_range_func
            current_opts['outtmpl'] = raw_filename

            try:
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    ydl.download([url])
                
                found = glob.glob(os.path.join(temp_dir, f"raw_{i:03d}*"))
                if not found:
                    print(f"   ⚠️ Error: Download failed for segment {i}")
                    continue
                
                downloaded_file = found[0]

                # 2. Get Video Dimensions for Responsive Layout
                vid_w, vid_h = get_video_dimensions(downloaded_file)
                
                # --- CALCULATE RELATIVE DIMENSIONS ---
                
                # Scoreboard (Bottom 15% of screen)
                sb_height = int(vid_h * 0.15)
                sb_y = vid_h - sb_height
                accent_height = max(2, int(vid_h * 0.006)) # 0.6% height
                
                # Score Boxes
                box_height = int(sb_height * 0.5)
                box_width = int(box_height * 1.2)
                box_y = sb_y + (sb_height - box_height) // 2
                
                # Center calculation
                center_x = vid_w // 2
                box_t1_x = center_x - box_width # Team 1 box left of center
                box_t2_x = center_x             # Team 2 box right of center
                
                # Font Sizes
                font_score = int(box_height * 0.8)
                font_team = int(sb_height * 0.25)
                
                # Text Offsets
                text_team_offset_x = int(box_width * 0.2) # padding from box
                
                # Progression Layout
                prog_margin_top = int(vid_h * 0.05)
                # Available height = Video Height - Top Margin - Scoreboard Height - Padding
                prog_available_h = vid_h - prog_margin_top - sb_height - int(vid_h * 0.02)
                
                # Line position
                prog_line_x = int(vid_h * 0.05) + 14 # Keep left margin relative to height
                prog_line_w = max(2, int(vid_h * 0.003))
                
                # Square sizes
                # Max square size is 5% of height, but shrink if too many segments
                prog_slot_h = min(prog_available_h / total_segs, vid_h * 0.05)
                prog_gap = max(1, int(prog_slot_h * 0.1))
                prog_box_dim = prog_slot_h - prog_gap

                # --- BUILD FILTER COMPLEX ---
                print(f"       🔥 Burning Graphics (Resolution: {vid_w}x{vid_h})...")
                
                filters = []

                # A. Progression Bar (Left Side)
                if show_progression:
                    # Draw vertical white line
                    filters.append(
                        f"drawbox=x={prog_line_x}:y={prog_margin_top}:w={prog_line_w}:h={int(prog_available_h)}:color=white@1:t=fill"
                    )
                    
                    for k in range(i + 1):
                        pt_winner = all_segments[k]['winner']
                        if pt_winner == 0: continue
                        
                        y_pos = int(prog_margin_top + k * prog_slot_h)
                        
                        if pt_winner == 1:
                            # Red (Left)
                            x_pos = int(prog_line_x - prog_gap - prog_box_dim)
                            color = "red@0.8"
                        else:
                            # Blue (Right)
                            x_pos = int(prog_line_x + prog_line_w + prog_gap)
                            color = "blue@0.8"
                            
                        filters.append(
                            f"drawbox=x={x_pos}:y={y_pos}:w={int(prog_box_dim)}:h={int(prog_box_dim)}:color={color}:t=fill"
                        )

                # B. Scoreboard (Bottom)
                
                # 1. Background Bar
                filters.append(f"drawbox=y={sb_y}:h={sb_height}:w={vid_w}:color=black@0.8:t=fill")
                # 2. Orange Accent
                filters.append(f"drawbox=y={sb_y}:h={accent_height}:w={vid_w}:color=orange@1:t=fill")
                
                # 3. Red Box (Team 1 Score)
                filters.append(f"drawbox=x={box_t1_x}:y={box_y}:w={box_width}:h={box_height}:color=red@0.8:t=fill")
                # 4. Blue Box (Team 2 Score)
                filters.append(f"drawbox=x={box_t2_x}:y={box_y}:w={box_width}:h={box_height}:color=blue@0.8:t=fill")
                
                # 5. Team 1 Name (Right aligned to Red Box)
                # anchor: top-right relative to box
                t1_text_x = box_t1_x - text_team_offset_x
                # Centered vertically in remaining scoreboard space? No, align with box center roughly
                text_y = box_y + (box_height - font_team)/2 # Rough vertical center
                
                filters.append(
                    f"drawtext=fontfile='{font_path}':text='{seg['t1_name']}':fontcolor=white:fontsize={font_team}:"
                    f"x={t1_text_x}-text_w:y={box_y}+(({box_height}-text_h)/2)"
                )
                
                # 6. Team 1 Score
                filters.append(
                    f"drawtext=fontfile='{font_path}':text='{seg['s1']}':fontcolor=white:fontsize={font_score}:"
                    f"x={box_t1_x}+(({box_width}-text_w)/2):y={box_y}+(({box_height}-text_h)/2)"
                )
                
                # 7. Team 2 Score
                filters.append(
                    f"drawtext=fontfile='{font_path}':text='{seg['s2']}':fontcolor=white:fontsize={font_score}:"
                    f"x={box_t2_x}+(({box_width}-text_w)/2):y={box_y}+(({box_height}-text_h)/2)"
                )
                
                # 8. Team 2 Name
                t2_text_x = box_t2_x + box_width + text_team_offset_x
                filters.append(
                    f"drawtext=fontfile='{font_path}':text='{seg['t2_name']}':fontcolor=white:fontsize={font_team}:"
                    f"x={t2_text_x}:y={box_y}+(({box_height}-text_h)/2)"
                )

                final_filter_str = ",".join(filters)

                cmd = [
                    "ffmpeg", "-i", downloaded_file,
                    "-vf", final_filter_str,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "copy",
                    "-y", final_filename
                ]

                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                downloaded_clips.append(final_filename)

                # Cleanup raw file
                try: os.remove(downloaded_file)
                except: pass

            except Exception as e:
                print(f"   ❌ Error processing segment {i}: {e}")

        # --- PHASE 2: CONCAT ---
        if downloaded_clips:
            print("\nMerging final video...")
            with open(list_file_path, 'w') as f:
                for clip in downloaded_clips:
                    safe_path = os.path.abspath(clip).replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")

            cmd_concat = [
                "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file_path,
                "-c", "copy", "-y", output_video
            ]
            subprocess.run(cmd_concat, check=True)
            print(f"\n✅ DONE! Video saved to: {output_video}")

    except Exception as e:
        print(f"\n❌ Critical Error: {e}")

    finally:
        # Cleanup
        print("🧹 Cleaning temp files...")
        if os.path.exists(list_file_path): os.remove(list_file_path)
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        if os.path.exists(processed_dir): shutil.rmtree(processed_dir)
        print("✨ Finished.")

if __name__ == "__main__":
    main()