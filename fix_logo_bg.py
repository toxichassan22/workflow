from PIL import Image

img = Image.open("manafe-logo.png").convert("RGBA")

white_bg = Image.new("RGBA", img.size, (255, 255, 255, 255))

white_bg.paste(img, mask=img.split()[3])

white_bg.convert("RGB").save("manafe-logo.png")

print("Done - background is now white")
