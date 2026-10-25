"""OCR official scanned municipal investment tables with auditable page references.
Requires system pdftoppm, tesseract rus and Pillow. Output is staging JSON.
"""
import csv,io,json,re,subprocess,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

BASE=Path(sys.argv[1])
KIND=sys.argv[2]
PDF=BASE/('education_full.pdf' if KIND=='education' else 'sports_pdf_http.bin')
OUT=BASE/('ocr_'+KIND)
OUT.mkdir(exist_ok=True)
PAGES=range(91,124) if KIND=='education' else range(113,130)
RIGHT=.239 if KIND=='education' else .272
IDEND=.094 if KIND=='education' else .089

def page(n):
 prefix=OUT/f'p{n}'
 imagepath=prefix.with_suffix('.png')
 if not imagepath.exists():
  subprocess.run(['pdftoppm','-f',str(n),'-l',str(n),'-scale-to','2400','-singlefile','-png',str(PDF),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 im=Image.open(imagepath).convert('L');w,h=im.size
 # A full-width line across the title cell separates investment objects.
 left=int(w*(IDEND+.004));right=int(w*(RIGHT-.004))
 strip=im.crop((left,0,right,h)).resize((1,h),Image.Resampling.BOX)
 ys=[y for y in range(int(h*.09),int(h*.97)) if strip.getpixel((0,y))<85]
 groups=[]
 for y in ys:
  if not groups or y>groups[-1][-1]+2:groups.append([y])
  else:groups[-1].append(y)
 bounds=[int(sum(g)/len(g)) for g in groups]
 crop=im.crop((int(w*.047),0,int(w*RIGHT),h))
 cropfile=OUT/f'p{n}_titles.png';crop.save(cropfile)
 tsvfile=OUT/f'p{n}.tsv'
 if not tsvfile.exists():
  proc=subprocess.run(['tesseract',str(cropfile),'stdout','-l','rus','--psm','6','tsv'],capture_output=True,check=True)
  tsvfile.write_bytes(proc.stdout)
 words=list(csv.DictReader(io.StringIO(tsvfile.read_text()),delimiter='\t'))
 result=[]
 for top,bottom in zip(bounds,bounds[1:]):
  if bottom-top<25:continue
  inside=[a for a in words if a.get('text','').strip() and top+2<=int(a['top'])+int(a['height'])/2<=bottom-2]
  numwords=[a['text'] for a in inside if int(a['left'])+int(a['width'])/2<w*(IDEND-.047)]
  number=''.join(numwords).replace(',','.').replace(':','.').strip(' .|')
  if not re.fullmatch(r'1\.\d{1,2}\.\d{1,2}',number):continue
  titlewords=[a for a in inside if int(a['left'])+int(a['width'])/2>=w*(IDEND-.047)]
  title=' '.join(a['text'] for a in titlewords).strip(' |')
  title=re.sub(r'(?<=[а-я])-[ ]+(?=[а-я])','',title)
  if len(title)<25:continue
  if not re.search('ремонт|строительств|реконструкц|устройство|обустройств|оснащен|школ|комплекс|благоустройств',title,re.I):continue
  confidence=sum(float(a['conf']) for a in titlewords)/max(1,len(titlewords))
  result.append({'page':n,'source_row':number+'.','title':title,'ocr_confidence':round(confidence,1)})
 return result

result=[]
with ThreadPoolExecutor(2) as pool:
 for n,rows in zip(PAGES,pool.map(page,PAGES)):
  result.extend(rows);print(KIND,n,len(rows),flush=True)
(OUT/'objects.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('TOTAL',len(result),flush=True)
