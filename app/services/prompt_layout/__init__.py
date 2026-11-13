"""How a chat's notes and skills are laid out in the prompt so changing them costs the engine little re-reading
(Admin settings > Inference > Prompt cache): layouts.PromptLayouts picks one of ordered.py, append.py, index.py
(and "blocks", ordered.py). Kept empty of imports: chat_follow_up imports base.py, and index.py imports it back."""
