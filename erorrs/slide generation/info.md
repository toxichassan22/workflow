(index):5254 designer generate failed Error: Vision model failed on batch 1: {"error": {"message": "User not found.", "code": 401}}
    at generateDesignerDeck ((index):5251:17)
generateDesignerDeck @ (index):5254
await in generateDesignerDeck  
showDesignerPreview @ (index):5154
proceedFromMoodboard @ (index):4897
onclick @ (index):2985
[Designer] Generating full deck with 1 images in batches...
  Slides: 16 | Has images: 1
  [Designer Batch] Designing slides 1 of 16...
  [FAIL] Designer generation error: Vision model failed on batch 1: {"error": {"message": "User not found.", "code": 401}}
127.0.0.1 - - [03/Jul/2026 08:48:44] "POST /api/designer-generate HTTP/1.1" 500 -
