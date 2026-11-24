"""Link worker against an already-built, pinned MLX Swift port. No fetching/installing.
Usage: python3 build-existing.py --build EXISTING_DERIVED_DATA --output PRIVATE_TRIAL
"""
import argparse,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--build',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();b=a.build.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
products=b/'Build/Products/Release';checkouts=b/'SourcePackages/checkouts'
cmd=['xcrun','swiftc','-O','-swift-version','6','-target','arm64-apple-macos14.0','-module-cache-path',str(out/'module-cache'),'-I',str(products),'-Xcc','-fmodule-map-file='+str(b/'Build/Intermediates.noindex/GeneratedModuleMaps/cLogSupport.modulemap')]
for path in [checkouts/'swift-numerics/Sources/_NumericsShims/include',checkouts/'mlx-swift/Source/cLogSupport/include',checkouts/'mlx-swift/Source/Cmlx/include']:
 cmd+=['-Xcc','-I'+str(path)]
cmd+=[str(Path(__file__).with_name('worker.swift'))]+[str(products/(n+'.o')) for n in ['VoiceIsolatorMLX','MLX','Cmlx','cLogSupport','Numerics','RealModule','ComplexModule','_NumericsShims']]
cmd+=['-lc++','-framework','Metal','-framework','Foundation','-framework','Accelerate','-o',str(out/'voice-isolate-worker')]
subprocess.run(cmd,check=True)
shutil.copytree(products/'mlx-swift_Cmlx.bundle',out/'mlx-swift_Cmlx.bundle',dirs_exist_ok=True)
