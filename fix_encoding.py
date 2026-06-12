with open('backend/services/translation.py', 'rb') as f:
    raw = f.read()

# Replace common Unicode sequences that get corrupted
replacements = [
    (b'\xe2\x80\x94', b' - '),   # em dash
    (b'\xe2\x80\x93', b'-'),      # en dash
    (b'\xe2\x80\x99', b"'"),      # right single quote
    (b'\xe2\x80\x9c', b'"'),      # left double quote
    (b'\xe2\x80\x9d', b'"'),      # right double quote
]
fixed = raw
for old, new in replacements:
    fixed = fixed.replace(old, new)

try:
    fixed.decode('utf-8')
    with open('backend/services/translation.py', 'wb') as f:
        f.write(fixed)
    print('Fixed and saved successfully')
except Exception as e:
    print('Still has issues:', e)
    # Show remaining non-ascii bytes
    for i, b in enumerate(fixed):
        if b > 127:
            print(f'  byte {b:#04x} at pos {i}: ...{fixed[max(0,i-10):i+10]}...')
