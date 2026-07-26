import sys
import os

# 1. Base directory ka path
base_dir = os.path.dirname(__file__)
sys.path.insert(0, base_dir)

# 2. Virtual Environment Python Interpreter path (Apne exact virtualenv path se replace karein)
# Agar aap cPanel Setup Python App use kar rahe hain to path aam taur par Aisa hota hai:
# INTERP = os.path.expanduser('~/virtualenv/gsms_git/3.10/bin/python')
INTERP = '/home/faizanso/virtualenv/gsms_git/3.10/bin/python'  # Apne path ke hisab se verify kar lein
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# 3. Django Settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gsms.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()