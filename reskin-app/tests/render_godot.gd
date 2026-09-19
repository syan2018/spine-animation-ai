extends SceneTree
## Run with a graphical renderer and --path pointing to an exported project.
## Saves setup and fixed-time animation renders under that project's qa folder.

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var demo = load("res://demo.tscn").instantiate()
	root.add_child(demo)
	var character = demo.get_node("Character")
	var player: AnimationPlayer = character.get_node("AnimationPlayer")
	DirAccess.make_dir_recursive_absolute("res://qa")
	var shots: Array = []
	var index := 0
	for skin in character.skins:
		character.set_skin(skin)
		for clip in player.get_animation_list():
			var animation := player.get_animation(clip)
			var times: Array = [0.0] if clip == "RESET" else [0.0, animation.length * 0.5, max(0.0, animation.length - 0.001)]
			for time in times:
				player.play(clip, 0)
				player.seek(time, true)
				player.pause()
				await process_frame
				await RenderingServer.frame_post_draw
				var filename := "qa/frame_%03d.png" % index
				var image := root.get_texture().get_image()
				if image == null or image.is_empty():
					push_error("No graphical frame; run without --headless")
					quit(1)
					return
				image.save_png("res://" + filename)
				shots.append({"skin": skin, "clip": clip, "time": time, "file": filename})
				index += 1
	var manifest := FileAccess.open("res://qa/frames.json", FileAccess.WRITE)
	manifest.store_string(JSON.stringify(shots, "  "))
	manifest.close()
	print("RENDER_QA_OK ", index)
	quit()
