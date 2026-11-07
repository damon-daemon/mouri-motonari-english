"""bwipe.py (testing only): mark every live enemy unit (battle array 30..89) retreated and clear its grid cell; then End Phase -> victory check. Run bkill first (scripted reinforcements)."""
import sys; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__))); import ram, gdbmem
r=ram.shm(); g=gdbmem.G(); b=0x800c3b08
for i in range(30,90):
    u=r[0xc3b08+0x24*i:][:0x24]
    if u[4]!=i or u[0:2]==b'\xff\xff' or u[0xb] in (0,4): continue
    if u[5]!=0xff:
        c=0x800e3ed4+u[6]*20+u[5]
        if r[c-0x80000000]==i: g.cmd('M%x,1:ff'%c)
    g.cmd('M%x,1:04'%(b+0x24*i+0xb)); print('wiped',i)
g.resume()
