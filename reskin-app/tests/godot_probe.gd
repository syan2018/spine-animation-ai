extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var character = load("res://character.tscn").instantiate()
	root.add_child(character)
	var model = JSON.parse_string(FileAccess.get_file_as_string("res://character.json"))
	var cases = JSON.parse_string(FileAccess.get_file_as_string("res://probe_cases.json"))
	var paths = JSON.parse_string(FileAccess.get_file_as_string("res://probe_paths.json"))
	var player = character.get_node("AnimationPlayer")
	var result: Array = []
	for sample in cases:
		player.play(sample.clip, 0)
		player.seek(sample.time, true)
		var poses: Dictionary = {}
		for bone in paths:
			var transform: Transform2D = character.get_node(paths[bone]).global_transform
			poses[bone] = [transform.x.x, transform.x.y, transform.y.x, transform.y.y, transform.origin.x, transform.origin.y]
		result.append(poses)
	# Verify that all skins really update the native sprites, including transforms.
	for skin in model.skins:
		assert(character.set_skin(skin))
		for slot in model.skins[skin]:
			var sprite: Sprite2D = character.get_node(character.parts[slot])
			var att = model.skins[skin][slot]
			assert(sprite.visible == (att != null))
			if att != null:
				assert(sprite.texture != null)
				assert(sprite.texture.resource_path == "res://" + att.texture)
				assert(sprite.position.distance_to(Vector2(att.x, -att.y)) < 0.001)
				assert(abs(sprite.rotation + deg_to_rad(att.rotation)) < 0.001)
				var expected_scale := Vector2(att.scaleX * att.width / sprite.texture.get_width(), att.scaleY * att.height / sprite.texture.get_height())
				assert(sprite.scale.distance_to(expected_scale) < 0.001)
				assert(not sprite.z_as_relative)
	character.reset_pose()
	for bone in model.bones:
		var node: Bone2D = character.get_node(paths[bone.name])
		assert(node.transform.is_equal_approx(node.rest))
	var file = FileAccess.open("res://probe_result.json", FileAccess.WRITE)
	file.store_string(JSON.stringify(result))
	file.close()
	character.queue_free()
	await process_frame
	print("GODOT_PROBE_OK")
	quit()
