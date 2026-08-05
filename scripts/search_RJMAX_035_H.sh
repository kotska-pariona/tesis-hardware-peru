set -e
grep -RIn --exclude-dir=.git --exclude=*.png --exclude=*.jpg --exclude=*.jpeg --exclude=*.gif \
  -e "RJ_MAX" -e "rj_max" -e "0.35" .
