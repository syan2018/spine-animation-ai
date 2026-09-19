extends Node2D
## Native cutout character. These resources can be moved together into a project.

@export var skins: Dictionary = {}
@export var parts: Dictionary = {}
@export var current_skin: String = "default"
@export var hidden_parts: Array[String] = []
var _hidden_parts: Dictionary = {}

func _ready() -> void:
	for slot in hidden_parts:
		_hidden_parts[slot] = true
	set_skin(current_skin)

func set_skin(skin_name: String) -> bool:
	if not skins.has(skin_name):
		push_error("Unknown skin: " + skin_name)
		return false
	for slot in parts:
		var sprite := get_node(NodePath(parts[slot])) as Sprite2D
		var attachment: Dictionary = skins[skin_name].get(slot, {})
		sprite.visible = not attachment.is_empty() and not _hidden_parts.get(slot, false)
		if attachment.is_empty():
			continue
		sprite.texture = attachment.texture
		sprite.position = attachment.position
		sprite.rotation = attachment.rotation
		sprite.scale = attachment.scale
		sprite.self_modulate = attachment.color
	current_skin = skin_name
	return true

func set_part_visible(slot: String, shown: bool) -> void:
	if parts.has(slot):
		_hidden_parts[slot] = not shown
		set_skin(current_skin)

func play_animation(clip: String, blend_seconds: float = 0.15) -> void:
	var player := $AnimationPlayer as AnimationPlayer
	if player.has_animation(clip):
		player.play(clip, blend_seconds)
	else:
		push_error("Unknown animation: " + clip)

func reset_pose() -> void:
	var player := $AnimationPlayer as AnimationPlayer
	player.play("RESET")
	player.advance(0)
	player.stop(true)
