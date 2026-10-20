// LogicRF Technologies: offline H102 Windows profile generator.
// Use user-supplied ADI SDK interfaces to generate complete profile/stream files without hardware.
// The PowerShell entry verifies SDK inputs and outputs; device loading requires separate qualification.
// 2026-10-07
using System;
using System.IO;
using System.Reflection;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
class H102ProfileGenerator {
 class Request { public string id; public uint rate, bandwidth, corner; public string adcRate="HIGH", loTopology="independent"; }
 static string dllRoot;
 static Assembly sdk;
 static Assembly Resolve(object sender, ResolveEventArgs e) {
  string p=Path.Combine(dllRoot,new AssemblyName(e.Name).Name+".dll");
  return File.Exists(p)?Assembly.LoadFrom(p):null;
 }
 static Type T(string n) {return sdk.GetType("AnalogDevices.Adrv9001."+n,true);}
 static object New(string n) {return Activator.CreateInstance(T(n));}
 static void Set(object o,string n,object v) {
  var p=o.GetType().GetProperty(n);
  var x=p.PropertyType.IsEnum?Enum.Parse(p.PropertyType,(string)v):(p.PropertyType.IsInstanceOfType(v)?v:Convert.ChangeType(v,p.PropertyType));
  p.SetValue(o,x,null);
 }
 static object Get(object o,string n) {return o.GetType().GetProperty(n).GetValue(o,null);}
 static void Errors() {
  var t=T("ErrorHandler");
  foreach(string n in new[]{"ErrorCount","Errors","Messages"}) {
   var x=t.GetMethod(n).Invoke(null,null);Console.WriteLine(n+" "+x);
   var xs=x as IEnumerable;if(xs!=null && !(x is string))foreach(var item in xs)Console.WriteLine("  "+item);
  }
 }
 static void Version(string method) {
  var v=T("ProfileGen").GetMethod(method).Invoke(null,null);
  Console.WriteLine(method+" "+v);
  foreach(var f in v.GetType().GetFields())Console.WriteLine(f.Name+" "+f.GetValue(v));
  foreach(var p in v.GetType().GetProperties())Console.WriteLine(p.Name+" "+p.GetValue(v,null));
 }
 static int Main(string[] args) {
  try {
   if(args.Length!=3 && args.Length!=4)throw new ArgumentException("Expected DLL directory, C0 top-level file, new output directory, optional request TSV");
   dllRoot=Path.GetFullPath(args[0]);AppDomain.CurrentDomain.AssemblyResolve+=Resolve;
   sdk=Assembly.LoadFrom(Path.Combine(dllRoot,"AnalogDevices.Adrv9001.ProfileGen.dll"));
   string topLevel=Path.GetFullPath(args[1]);string output=Path.GetFullPath(args[2]);
   if(Directory.Exists(output))throw new IOException("Output directory must be new");
   var requests=new List<Request>();var ids=new HashSet<string>();
   if(args.Length==4) {
    foreach(string line in File.ReadAllLines(args[3])) {
     string[] cells=line.Split('\t');
     if((cells.Length<4 || cells.Length>6) || !Regex.IsMatch(cells[0],"^[a-z0-9][a-z0-9-]{0,63}$") || !ids.Add(cells[0]))throw new ArgumentException("Invalid or duplicate request ID");
     var r=new Request{id=cells[0],rate=UInt32.Parse(cells[1],CultureInfo.InvariantCulture),bandwidth=UInt32.Parse(cells[2],CultureInfo.InvariantCulture),corner=UInt32.Parse(cells[3],CultureInfo.InvariantCulture)};
     if(cells.Length>=5)r.adcRate=cells[4];
     if(cells.Length==6)r.loTopology=cells[5];
     if(r.loTopology!="independent" && r.loTopology!="shared-lo2")throw new ArgumentException("Invalid LO topology");
     if(r.adcRate!="HIGH" && r.adcRate!="MED" && r.adcRate!="LOW")throw new ArgumentException("Invalid ADC clock rate choice");
     if(r.rate==0 || r.rate>61440000 || r.bandwidth<12000 || r.bandwidth>40000000 || r.bandwidth>r.rate || r.corner==0)throw new ArgumentException("Request outside H102 generation bounds");
     requests.Add(r);
    }
    if(requests.Count==0 || requests.Count>128)throw new ArgumentException("Empty or excessive request count");
   } else foreach(uint rate in new uint[]{40000000,20000000,8000000})requests.Add(new Request{id=(rate/1000000)+"msps-"+(rate/2000000)+"mhz",rate=rate,bandwidth=rate/2,corner=rate==8000000?3000u:rate/4000});
   Directory.CreateDirectory(output);Version("Version_Get");Version("StreamGenVersion_Get");
   int failures=0;
   foreach(var request in requests) {
    uint rate=request.rate;string id=request.id;string dir=Path.Combine(output,id);Directory.CreateDirectory(dir);
    Console.WriteLine("BEGIN "+id);
    try {
     var b=New("Adrv9001Blueprint");Set(b,"deviceClockInput_kHz",300000u);Set(b,"duplex","FDD");Set(b,"processorClockDivisor","DIVISOR_1");Set(b,"adcRate",request.adcRate);
     foreach(string name in new[]{"rxChannel1","rxChannel2","txChannel1","txChannel2"}) {
      var c=Get(b,name);Set(c,"channelFilter",new int[128]);Set(c,"enabled",true);Set(c,"samplingRate_Hz",rate);Set(c,"rfChannelBandwidth_Hz",request.bandwidth);
      Set(c,"ssiType","ADRV9001_SSI_TYPE_LVDS");Set(c,"ssiNumLane","ADRV9001_SSI_2_LANE");Set(c,"ssiDataRate","DOUBLE");
      Set(c,"ssiDataFormat","ADRV9001_SSI_FORMAT_16_BIT_I_Q_DATA");Set(c,"ssiInterfaceRate_Hz",rate);
      if(name.StartsWith("rx")) { Set(c,"rfInput","ADRV9001_RX_A"); Set(c,"analogFilterCorner_kHz",request.corner); }
      // Native blueprint channels are copied on assignment; set the modified channel back.
      SetChannel(b,name,c);
     }
     if(request.loTopology=="shared-lo2") {
      // Use the public blueprint mapping interface to generate both profile and stream.
      var mapping=New("LoMapping");
      foreach(string port in new[]{"rxChannels","txChannels"}) {
       var field=mapping.GetType().GetField(port);var channels=(Array)field.GetValue(mapping);
       for(int i=0;i<channels.Length;i++)channels.SetValue(Enum.Parse(channels.GetType().GetElementType(),"ADRV9001_LOSEL_LO2"),i);
       field.SetValue(mapping,channels);
      }
      object[] mappingArgs={mapping};
      var mapped=T("Adrv9001Blueprint").GetMethod("LoMapping_Overwrite").Invoke(b,mappingArgs);
      if(Convert.ToInt32(mapped)!=0)throw new Exception("LO mapping overwrite unsuccessful");
     }
     T("Adrv9001Blueprint").GetMethod("Save").Invoke(b,new object[]{Path.Combine(dir,"request-blueprint.json")});
     var architect=New("ProfileArchitect");object[] develop={New("Profile"),New("DesignSummary"),b,true};
     MethodInfo method=null;foreach(var m in T("ProfileArchitect").GetMethods())if(m.Name=="Profile_Develop"&&m.GetParameters().Length==4)method=m;
     var result=method.Invoke(architect,develop);Console.WriteLine("DEVELOP_RESULT "+result);Errors();
     if(Convert.ToInt32(result)!=0||develop[0]==null)throw new Exception("Profile_Develop unsuccessful");
     RejectDiagnostics();
     var profile=develop[0];
     T("Profile").GetMethod("Save").Invoke(profile,new object[]{Path.Combine(dir,"profile.json"),Enum.Parse(T("ProfileSaveMethod"),"JSON_NATIVE")});
     T("Profile").GetMethod("StreamSettings_Save").Invoke(profile,new object[]{Path.Combine(dir,"stream-settings.json")});
     var sm=T("Profile").GetMethod("StreamImage_Save",new Type[]{typeof(string),typeof(string)});
     sm.Invoke(profile,new object[]{Path.Combine(dir,"stream.bin"),topLevel});
     RejectDiagnostics();
     File.WriteAllText(Path.Combine(dir,"generation-pass.json"),"{\"success\":true,\"warnings_rejected\":true}");
     Console.WriteLine("COMPLETE "+id);
    }catch(Exception ex){failures++;Console.WriteLine("FAILED "+id+" "+ex);Errors();}
   }
   return failures==0?0:1;
  }catch(Exception ex){Console.WriteLine(ex);return 2;}
 }
 static void RejectDiagnostics() {
  var messages=(IEnumerable)T("ErrorHandler").GetMethod("Messages").Invoke(null,null);
  foreach(var item in messages) {
   string text=Convert.ToString(item);
   if(text.IndexOf("WARNING:",StringComparison.OrdinalIgnoreCase)>=0 || text.IndexOf("ERROR:",StringComparison.OrdinalIgnoreCase)>=0)
    throw new Exception("SDK diagnostic rejected: "+text);
  }
 }
 static void SetChannel(object o,string n,object v){o.GetType().GetProperty(n).SetValue(o,v,null);}
}
