#!/system/bin/sh
# Redirect the client's .hash sidecar writes into a shell-readable directory.
# The app creates the sidecar with a plain buffered write, so a symlink at that path
# is followed; the installed .db itself is rename-swapped in, which a symlink cannot catch.
B=/storage/emulated/0/Android/data/com.klab.lapis/files
M=$B/server/mirror
mkdir -p $M; chmod 777 $M
OUT=/data/local/tmp/mirror.log
: > $OUT
i=0
while [ $i -lt 900 ]; do
  i=$((i+1))
  for n in JP/master_data_lang.db MasterData/master_data.db; do
    h="$B/$n.hash"
    base=$(basename $n)
    want=$M/$base.hash
    if [ ! -L "$h" ]; then
      rm -f "$h" 2>/dev/null
      ln -s "$want" "$h" 2>>$OUT && echo "linked $n -> $want" >> $OUT
    fi
  done
  sleep 0.1
done
echo DONE >> $OUT
