"""Generate an uncompressed, fully editable draw.io AWS reference diagram."""
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent / 'diagrams'
doc = ET.Element('mxfile', host='app.diagrams.net', agent='HelixFlow', version='26.0.0')
COLORS = {'compute':'#ED7100','integration':'#E7157B','storage':'#7AA116',
          'database':'#C925D1','management':'#E7157B','network':'#8C4FFF'}

class Page:
    def __init__(self, name, height=1100):
        page = ET.SubElement(doc, 'diagram', id=name.split()[0], name=name)
        model = ET.SubElement(page, 'mxGraphModel', dx='1500', dy=str(height), grid='1',
            gridSize='10', guides='1', tooltips='1', connect='1', arrows='1', fold='1',
            page='1', pageScale='1', pageWidth='1000', pageHeight=str(height), math='0', shadow='0')
        self.root = ET.SubElement(model,'root')
        ET.SubElement(self.root,'mxCell',id='0')
        ET.SubElement(self.root,'mxCell',id='1',parent='0')
        self.n = 1
    def cell(self, label, x,y,w,h,style='',parent='1'):
        self.n += 1
        node=ET.SubElement(self.root,'mxCell',id=str(self.n),value=label,
            style='html=1;whiteSpace=wrap;fontFamily=Helvetica;fontSize=15;fontColor=#232F3E;'+style,
            vertex='1',parent=parent)
        ET.SubElement(node,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),attrib={'as':'geometry'})
        return str(self.n)
    def text(self,label,x,y,w,h=32,size=16):
        return self.cell(label,x,y,w,h,f'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize={size};')
    def panel(self,label,x,y,w,h,dashed=False):
        return self.cell(label,x,y,w,h,'rounded=1;arcSize=4;fillColor=#F8FAFC;strokeColor=#9AA9B7;'+
            'verticalAlign=top;align=left;spacingTop=12;spacingLeft=14;fontStyle=1;'+('dashed=1;' if dashed else ''))
    def service(self,label,icon,x,y,w=200,h=100,category='compute',dashed=False):
        color=COLORS[category]
        group=self.cell('',x,y,w,h,'group;fillColor=none;strokeColor=none;')
        self.cell('',0,0,w,h,'rounded=1;arcSize=8;fillColor=#FFFFFF;strokeColor='+color+';'+
                  ('dashed=1;' if dashed else ''),parent=group)
        self.cell('',10,(h-34)/2,34,34,'shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.'+icon+
                  ';fillColor='+color+';strokeColor=#FFFFFF;gradientColor=none;aspect=fixed;',parent=group)
        self.cell(label,52,6,w-60,h-12,'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=15;',parent=group)
        return group
    def edge(self,a,b,label='',color='#485B6A',dashed=False,points=(),ports='',label_offset=None):
        self.n+=1
        e=ET.SubElement(self.root,'mxCell',id=str(self.n),value=label,edge='1',parent='1',source=a,target=b,
            style='edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;'+
            'strokeWidth=1.5;fontFamily=Helvetica;fontSize=14;labelBackgroundColor=#FFFFFF;strokeColor='+color+';'+ports+
            ('dashed=1;dashPattern=5 3;' if dashed else ''))
        g=ET.SubElement(e,'mxGeometry',relative='1',attrib={'as':'geometry'})
        if label_offset:
            ET.SubElement(g,'mxPoint',x=str(label_offset[0]),y=str(label_offset[1]),attrib={'as':'offset'})
        if points:
            arr=ET.SubElement(g,'Array',attrib={'as':'points'})
            for x,y in points: ET.SubElement(arr,'mxPoint',x=str(x),y=str(y))

p=Page('01 Execution architecture')
p.text('HelixFlow | AWS execution architecture',20,15,960,38,24)
p.text('Reference backend: infrastructure code exists; cloud deployment has not been validated.',20,60,960,28,15)
user=p.cell('Researcher\nBrowser / API',20,130,130,100,'rounded=1;fillColor=#EAF2F8;strokeColor=#466782;')
alb=p.service('Application\nLoad Balancer\nHTTP ingress','elastic_load_balancing',190,130,240,100,'network')
api=p.service('ECS / Fargate\nFastAPI container','fargate',465,130,240)
queue=p.service('SQS\nSubmission queue','sqs',740,130,240,category='integration')
dispatch=p.service('Lambda\nDispatcher','lambda',740,270,240,80)
sfn=p.service('Step Functions\nStage orchestration','step_functions',465,270,240,80,'integration')
for a,b in [(user,alb),(alb,api),(api,queue),(queue,dispatch),(dispatch,sfn)]: p.edge(a,b)
p.text('AWS Batch execution\nManaged EC2 capacity: zero to configured vCPU limit',20,270,420,70,16)
cpu=p.service('Batch CPU queue\nMSA preparation','batch',20,410,210)
rank=p.service('Optional Lambda\nFair-share ID\n+ priority','lambda',270,410,210)
spot=p.service('Batch GPU queue\nSpot inference','batch',520,410,210)
od=p.service('Batch GPU queue\nOn-Demand\nfallback','batch',770,410,210)
p.edge(sfn,cpu,'start',points=[(585,380),(125,380)],ports='exitX=0.5;exitY=1;entryX=0.5;entryY=0;')
p.edge(cpu,rank)
p.edge(rank,spot)
p.edge(spot,od,'catch',color='#A85A00',dashed=True,label_offset=(0,-16))
cpuvm=p.service('EC2 CPU\nMSA container\nc7i / m7i','ec2',20,560,210,110)
spotvm=p.service('EC2 GPU Spot\nBoltz container\ng5 / g6 / g6e','ec2',520,560,210,110)
odvm=p.service('EC2 GPU\nOn-Demand\nBoltz container','ec2',770,560,210,110)
for a,b in [(cpu,cpuvm),(spot,spotvm),(od,odvm)]: p.edge(a,b,'runs on')
p.cell('Batch selects capacity.\nPriority projection is not\nthe portable UAF-SJF\npolicy.',270,560,210,110,
       'rounded=1;fillColor=#F0F5F9;strokeColor=#9AA9B7;')
final=p.service('Finalizer Lambda\nInventory +\nhash checks','lambda',520,730,210)
p.edge(spotvm,final,'success')
p.edge(odvm,final,'success',points=[(875,780)])
p.cell('Integration work remains\nMSA binding; failure classification;\nattempt-aware state and publication;\nauthenticated HTTPS ingress.',20,720,460,110,
       'rounded=1;fillColor=#FFF8EE;strokeColor=#B77A23;align=left;spacing=12;')
p.text('Shared services (asset and event connections on the companion page)',20,865,960,30,16)
p.service('S3\nInputs / MSAs\nOutputs','s3',20,910,210,category='storage')
p.service('DynamoDB\nJob metadata\nArtifact pointers','dynamodb',270,910,210,category='database')
p.service('ECR\nAPI / MSA /\nBoltz images','ecr',520,910,210)
p.service('Planned: FSx\nfor Lustre\nMSA database','fsx_for_lustre',770,910,210,100,'storage',True)
p.text('Solid: logical flow / defined services. Dashed arrow: fallback. Dashed box: not provisioned.',20,1040,960,30,15)

p=Page('02 Assets events and operations')
p.text('HelixFlow | Assets, events and operations',20,15,960,38,24)
p.text('Reference backend: logical data flows and operational services, not validated cloud behavior.',20,60,960,28,15)
for title,x in [('Scientific data',20),('Batch events',345),('Images and monitoring',670)]:
    p.panel(title,x,110,310,830)
si=p.service('S3 inputs\nYAML + input assets','s3',35,165,280,85,'storage')
work=p.service('Batch workers\nCPU / GPU containers','batch',35,300,280,85)
so=p.service('S3 attempt prefixes\nPrepared data / outputs','s3',35,435,280,85,'storage')
fin=p.service('Finalizer Lambda\nSize / SHA-256 checks','lambda',35,570,280,85)
db=p.service('DynamoDB\nState + output pointer','dynamodb',35,705,280,85,'database')
for a,b,label in [(si,work,'read inputs'),(work,so,'write artifacts'),(so,fin,'verify objects'),(fin,db,'update metadata')]:p.edge(a,b,label,color='#007F73')
bat=p.service('AWS Batch\nJob state changes','batch',360,165,280,85)
ev=p.service('EventBridge\nBatch event rule','eventbridge',360,300,280,85,'integration')
rec=p.service('Reconciler Lambda\nState-change events','lambda',360,435,280,85)
ddb=p.service('DynamoDB\nJob status updates','dynamodb',360,570,280,85,'database')
for a,b in [(bat,ev),(ev,rec),(rec,ddb)]:p.edge(a,b,'event / state')
p.cell('Recovery caveats\nReconciliation and single-winner\npublication remain incomplete.\nNo exactly-once claim.',360,705,280,110,
       'rounded=1;fillColor=#FFF8EE;strokeColor=#B77A23;align=left;spacing=12;')
ecr=p.service('ECR images\nAPI / MSA / Boltz','ecr',685,165,280,85)
targets=p.cell('Image consumers\nFargate API + Batch workers',685,300,280,85,
               'rounded=1;fillColor=#F0F5F9;strokeColor=#9AA9B7;')
p.edge(ecr,targets,'pull images')
dlq=p.service('SQS dead-letter queue\nFailed submission delivery','sqs',685,435,280,85,'integration')
cw=p.service('CloudWatch\nDLQ alarm + logs','cloudwatch_2',685,570,280,85,'management')
sns=p.service('SNS\nOptional email alert','sns',685,705,280,85,'integration')
p.edge(dlq,cw,'queue depth metric')
p.edge(cw,sns,'alarm action')
p.text('S3 writes and metadata updates\nare separate operations.',35,840,280,65,15)
p.text('API / Lambda / worker logs\nto CloudWatch. Budget emails\nare configured separately.',685,835,280,85,15)
p.cell('Deployment and access\nTerraform; IAM roles and security groups; CI tests, lint and validation. Default VPC/subnets.\nNo tested production isolation, authenticated HTTPS, or deployed CI/CD claim.',20,975,960,100,
       'rounded=1;fillColor=#F0F5F9;strokeColor=#9AA9B7;align=left;spacing=14;')

OUT.mkdir(parents=True,exist_ok=True)
ET.indent(doc,space='  ')
target=OUT/'aws_infrastructure.drawio'
ET.ElementTree(doc).write(target,encoding='utf-8',xml_declaration=True)
for page in doc.findall('diagram'):
    cells=page.findall('./mxGraphModel/root/mxCell')
    ids=[c.get('id') for c in cells]
    assert len(ids)==len(set(ids))
    for c in cells:
        for attr in ('parent','source','target'):
            assert c.get(attr) is None or c.get(attr) in ids
print(target)
print('Validated 2 pages: unique cell IDs and all parent/edge references resolve.')
