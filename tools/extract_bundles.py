import UnityPy, pathlib, hashlib
for p in [r'C:\lapisbuild\device_files\files\JP\AssetBundles\assets\products\resources\luajit32.bdl',r'C:\lapisbuild\device_files\files\JP\AssetBundles\assets\products\resources\luajit64.bdl',r'C:\lapisbuild\luadata.bdl']:
 try:
  env=UnityPy.load(p); print('\nBUNDLE',p,len(env.objects))
  out=pathlib.Path(r'C:\lapisbuild\raw_'+pathlib.Path(p).stem); out.mkdir(exist_ok=True)
  n=0
  for o in env.objects:
   if o.type.name=='TextAsset':
    d=o.read(); b=d.m_Script.encode('utf-8','surrogateescape'); (out/d.m_Name).write_bytes(b); n+=1
  print('saved',n,'files',list(out.iterdir())[:3])
 except Exception as e: print('ERR',e)
