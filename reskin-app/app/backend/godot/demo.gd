extends Node2D
## Minimal runnable preview; the character scene has no dependency on this UI.

func _ready() -> void:
	var character := $Character
	var player := $Character/AnimationPlayer as AnimationPlayer
	var layer := CanvasLayer.new()
	add_child(layer)
	var bar := HBoxContainer.new()
	bar.position = Vector2(20, 20)
	bar.add_theme_constant_override("separation", 12)
	layer.add_child(bar)
	var label := Label.new()
	label.text = "Native Godot cutout"
	bar.add_child(label)
	var animations := OptionButton.new()
	animations.add_item("Rest pose")
	for clip in player.get_animation_list():
		if clip != "RESET":
			animations.add_item(clip)
	bar.add_child(animations)
	animations.item_selected.connect(func(index: int):
		if index == 0:
			character.reset_pose()
		else:
			character.play_animation(animations.get_item_text(index)))
	var looks := OptionButton.new()
	for skin in character.skins:
		looks.add_item(skin)
		if skin == character.current_skin:
			looks.select(looks.item_count - 1)
	bar.add_child(looks)
	looks.item_selected.connect(func(index: int): character.set_skin(looks.get_item_text(index)))
