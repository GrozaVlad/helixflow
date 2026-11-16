"""Generate editable overview and local-execution draw.io diagrams.

This resets manual diagram edits. Export existing .drawio files separately with
generate_architecture.py; they remain the authoritative editable artwork.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent / 'diagrams'
BLUE, TEAL, ORANGE = '#0072B2', '#007F73', '#A85A00'


class Diagram:
    def __init__(self, name, height=1020):
        self.doc = ET.Element('mxfile', host='app.diagrams.net', version='32.6.10')
        page = ET.SubElement(self.doc, 'diagram', id=name, name=name.replace('_', ' ').title())
        graph = ET.SubElement(page, 'mxGraphModel', grid='1', gridSize='10', guides='1',
            page='1', pageScale='1', pageWidth='1000', pageHeight=str(height), math='0', shadow='0')
        self.root = ET.SubElement(graph, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.n = 1

    def box(self, label, x, y, w, h, parent='1', color='#9AA9B7', fill='#FFFFFF', size=15, extra=''):
        self.n += 1
        cell = ET.SubElement(self.root, 'mxCell', id=str(self.n), value=label,
            vertex='1', parent=parent, style=f'rounded=1;arcSize=6;whiteSpace=wrap;html=1;'
            f'fontFamily=Helvetica;fontSize={size};fontColor=#263445;strokeColor={color};'
            f'fillColor={fill};spacing=8;{extra}')
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), attrib={'as':'geometry'})
        return str(self.n)

    def text(self, label, x, y, w, h, parent='1', size=15, extra=''):
        return self.box(label, x,y,w,h,parent,size=size,
            extra='text;strokeColor=none;fillColor=none;align=left;spacing=0;'+extra)

    def panel(self, label, x,y,w,h, parent='1', color='#9AA9B7', fill='#F8FAFC', dashed=False, size=21):
        return self.box(label,x,y,w,h,parent,color,fill,size,
            'container=1;collapsible=0;recursiveResize=0;verticalAlign=top;align=left;'
            'spacingTop=15;spacingLeft=18;fontStyle=1;'+('dashed=1;' if dashed else ''))

    def arrow(self, source, target, parent='1', color='#485B6A', label='', points=(), offset=None, ports=''):
        self.n += 1
        cell = ET.SubElement(self.root,'mxCell',id=str(self.n),value=label,edge='1',
            source=source,target=target,parent=parent,style='edgeStyle=orthogonalEdgeStyle;rounded=0;'
            f'html=1;endArrow=block;endFill=1;strokeColor={color};strokeWidth=2;'
            'fontFamily=Helvetica;fontSize=15;labelBackgroundColor=#FFFFFF;'+ports)
        g=ET.SubElement(cell,'mxGeometry',relative='1',attrib={'as':'geometry'})
        if offset:
            ET.SubElement(g,'mxPoint',x=str(offset[0]),y=str(offset[1]),attrib={'as':'offset'})
        if points:
            arr=ET.SubElement(g,'Array',attrib={'as':'points'})
            for x,y in points:
                ET.SubElement(arr,'mxPoint',x=str(x),y=str(y))

    def save(self, name):
        cells=self.root.findall('mxCell')
        ids={c.get('id') for c in cells}
        assert len(ids)==len(cells)
        for c in cells:
            for attr in ('parent','source','target'):
                assert c.get(attr) is None or c.get(attr) in ids
        OUT.mkdir(exist_ok=True)
        ET.indent(self.doc,space='  ')
        ET.ElementTree(self.doc).write(OUT/name,encoding='utf-8',xml_declaration=True)
        print(f'Validated and wrote {OUT/name}')


d=Diagram('general_architecture')
a=d.panel('(a) Define the scientific task',20,20,960,170)
for x,label in [
    (20,'Protein / ligand inputs\nYAML or supported FASTA'),
    (335,'Compatible MSAs + model assets\nInference settings and seed'),
    (650,'Submission context\nIndividual prediction or campaign\nOwner identity for CLI campaigns')]:
    d.box(label,x,65,290,80,a,fill='#FFFFFF')

b=d.panel('(b) Choose an execution environment',20,260,960,430)
d.text('Alternative interfaces and storage backends, not a single integrated control plane.',20,48,920,28,b)
for x,title,status,color,fill in [
    (20,'Interactive workbench','One local GPU',BLUE,'#F0F7FC'),
    (335,'Portable campaign runner','Evaluated on 1, 2 and 4 GPUs',TEAL,'#EFF8F5'),
    (650,'AWS reference backend','Experimental; not cloud-validated',ORANGE,'#FCF6EE')]:
    backend=d.panel(title,x,90,290,320,b,color,fill,dashed=(x==650),size=18)
    d.text(status,14,47,262,28,backend,size=14,extra=f'fontColor={color};')
    if x==20:
        first=d.box('Browser + FastAPI\nUpload, status, logs',14,90,262,62,backend,color)
        second=d.box('GPU lock + Boltz process\nOne prediction at a time',14,175,262,62,backend,color)
        d.arrow(first,second,backend,color)
        d.text('Persistent host files + model cache',14,268,262,38,backend,size=14,extra=f'fontColor={color};align=center;')
    elif x==335:
        first=d.box('CLI + durable SQLite queue\nInputs, jobs and attempts',14,90,262,62,backend,color)
        second=d.box('Runtime / memory estimates\nPolicy selection + GPU leases',14,175,262,62,backend,color)
        d.arrow(first,second,backend,color)
        pool=d.box('',14,268,262,34,backend,color,extra='group;strokeColor=none;fillColor=none;')
        for i in range(4):
            d.box(f'GPU {i}',i*67,0,61,34,pool,color,size=13,extra='rounded=0;spacing=0;')
        d.arrow(second,pool,backend,color)
    else:
        first=d.box('API / SQS / Step Functions\nDynamoDB job metadata',14,90,262,62,backend,color)
        second=d.box('Batch CPU and GPU containers\nEC2 Spot / On-Demand',14,175,262,62,backend,color)
        d.arrow(first,second,backend,color)
        d.text('S3 assets; ECR images',14,268,262,38,backend,size=14,extra=f'fontColor={color};align=center;')

c=d.panel('(c) Retain evidence and inspect results',20,760,960,195)
for x,label in [
    (20,'Structures + confidence outputs\nJob-specific Mol* inspection\nResearcher interpretation'),
    (335,'Inputs, settings, logs and hashes\nAttempt receipts + inventories\nTraceable campaign records'),
    (650,'Profiles, timings and owner metrics\nPolicy comparisons and reports\nOperational analysis')]:
    d.box(label,x,60,290,85,c)
d.text('Output categories depend on the selected workflow; columns do not denote one-to-one mappings.',20,155,920,26,c,size=14)
ports='exitX=0.5;exitY=1;entryX=0.5;entryY=0;'
d.arrow(a,b,label='Select a supported workflow',offset=(130,0),ports=ports)
d.arrow(b,c,label='Retain workflow-specific outputs',offset=(145,0),ports=ports)
d.text('No unified browser-to-multi-GPU control plane or shared cross-backend database is implied.',20,975,960,28,size=14)
d.save('general_architecture.drawio')

d=Diagram('local_execution',1000)
d.text('HelixFlow | Local execution interfaces',20,15,960,40,size=24,extra='fontStyle=1;')
d.text('Separate entry points with persistent host storage; the browser does not control the campaign runner.',20,65,960,35,size=15)
left=d.panel('(a) Interactive workbench',20,125,455,760,color=BLUE,fill='#F0F7FC')
right=d.panel('(b) Portable multi-GPU runner',525,125,455,760,color=TEAL,fill='#EFF8F5')
left_nodes=[]
right_nodes=[]
for i,label in enumerate([
    'Browser: YAML / FASTA upload\nSettings, status and logs',
    'FastAPI application\nGPU lock: one prediction at a time',
    'Boltz subprocess\nOne local GPU',
    'Host files and model cache\nStructures, confidence and requested affinity',
    'Downloads and Mol* viewer\nJob-specific results and failure logs']):
    left_nodes.append(d.box(label,30,85+i*130,395,85,left,BLUE,size=17))
for i,label in enumerate([
    'CLI campaign submission\nSnapshot inputs, MSAs, settings and hashes',
    'SQLite: durable jobs and attempts\nFeatures; runtime and memory estimates',
    'Coordinator: scheduling policy\nSelect waiting job; lease GPU by UUID',
    'One container; separate Boltz processes\nGPU 0     GPU 1     GPU 2     GPU 3',
    'Outputs, receipts and telemetry\nCheck hashes; publish results; export reports']):
    right_nodes.append(d.box(label,25,85+i*130,370,85,right,TEAL,size=17))
for parent,nodes,color in [(left,left_nodes,BLUE),(right,right_nodes,TEAL)]:
    for source,target in zip(nodes,nodes[1:]):
        d.arrow(source,target,parent,color)
d.arrow(right_nodes[-1],right_nodes[1],right,TEAL,points=[(425,647),(425,257)],
    ports='exitX=1;exitY=0.5;entryX=1;entryY=0.5;')
d.text('Frozen MSAs and cached model assets; no nested worker containers in the evaluated campaign runner.',20,920,960,45,size=16)
d.save('local_execution.drawio')
