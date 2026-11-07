"""bkill.py (testing only): enemy units (battle array 30..89) current End -> 0, player units -> 999"""
import sys,struct; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__))); import ram, gdbmem
r=ram.shm(); g=gdbmem.G()
for i in range(90):
    u=r[0xc3b08+0x24*i:][:8]
    rec=struct.unpack_from('<H',u)[0]
    if rec==0xffff: continue
    a=0x800b20d8+0x70*rec+0x68
    v=0 if i>=30 else 999
    g.cmd('M%x,4:%s'%(a,struct.pack('<I',v).hex()))
g.resume(); print('ok')
