from PIL import Image

def remove_white_bg(img_path, out_path, tolerance=30):
    img = Image.open(img_path).convert("RGBA")
    data = img.getdata()
    new_data = []
    for item in data:
        # Check if the pixel is white (with tolerance)
        if all(c >= 255 - tolerance for c in item[:3]):
            new_data.append((255, 255, 255, 0))
        else:
            # Preserve original alpha if not white
            new_data.append(item)
    img.putdata(new_data)
    img.save(out_path, "PNG")

remove_white_bg('app/static/dev/models/logo PT AKEBONO.png', 'app/static/dev/models/logo_akebono_nobg.png', tolerance=40)
print("Done")
