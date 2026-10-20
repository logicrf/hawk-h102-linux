/* Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
 * @file fake_iio.cpp
 * @brief Offline libiio fault substitute; never deploy in a hardware runtime environment.
 * @details LD_PRELOAD replaces context/buffer calls and records lifecycle cleanup.
 * @author LogicRF Technologies
 * @architect LogicRF
 * @email info@logicrf.com
 * @website https://www.logicrf.com
 * @version 1.0.0
 * @date 2026-10-16
 * @note No board connection, IQ continuity or RF behavior is verified here.
 */
#include <iio.h>
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>
#include <cerrno>
struct iio_context { int value; };
struct iio_device { int value; };
struct iio_channel { int index; };
struct iio_buffer { std::vector<char> bytes; };
static iio_context ctx{};
static iio_device dev{};
static iio_channel channels[]={{0},{1}};
static std::string profile="40msps-20mhz";
static unsigned long long ticket=0,config=1;
static bool fault(const char* s){const char* x=std::getenv("H102_FAKE_IIO_FAULT");return x && std::string(x)==s;}
static void audit(const char* s){if(const char* p=std::getenv("H102_FAKE_IIO_AUDIT")){std::ofstream f(p,std::ios::app);f<<s<<'\n';}}
extern "C" {
void iio_library_get_version(unsigned* major,unsigned* minor,char tag[8]){*major=fault("abi")?1:0;*minor=23;std::strcpy(tag,"test");}
iio_context* iio_create_context_from_uri(const char*){return &ctx;}
void iio_context_destroy(iio_context*){audit("context_destroy");}
int iio_context_set_timeout(iio_context*,unsigned){return 0;}
const char* iio_context_get_xml(const iio_context*){return "<context name=\"xml\"/>";}
iio_device* iio_context_find_device(const iio_context*,const char*){return &dev;}
unsigned iio_device_get_channels_count(const iio_device*){return 2;}
iio_channel* iio_device_get_channel(const iio_device*,unsigned i){return &channels[i];}
iio_channel* iio_device_find_channel(const iio_device*,const char* name,bool){int index=std::string(name).find('q')!=std::string::npos || std::string(name)=="voltage1";return index && fault("missing_q")?nullptr:&channels[index];}
void iio_channel_disable(iio_channel*){}
void iio_channel_enable(iio_channel*){}
long iio_channel_get_index(const iio_channel* c){return c->index;}
const iio_data_format* iio_channel_get_data_format(const iio_channel*){static iio_data_format f{16,16,0,true,true,false,false,1.0,1};f.shift=fault("format")?1:0;return &f;}
ssize_t iio_device_get_sample_size(const iio_device*){return 4;}
iio_buffer* iio_device_create_buffer(const iio_device*,size_t n,bool){audit("buffer_create");return new iio_buffer{std::vector<char>(n*4,42)};}
void iio_buffer_destroy(iio_buffer* b){audit("buffer_destroy");delete b;}
ssize_t iio_buffer_refill(iio_buffer* b){return fault("refill_errno")?-EPIPE:ssize_t(b->bytes.size()-(fault("short_refill")?4:0));}
ssize_t iio_buffer_push(iio_buffer* b){return fault("push_errno")?-EPIPE:ssize_t(b->bytes.size()-(fault("short_push")?4:0));}
void* iio_buffer_start(const iio_buffer* b){return const_cast<char*>(b->bytes.data());}
void* iio_buffer_end(const iio_buffer* b){return const_cast<char*>(b->bytes.data()+b->bytes.size());}
void* iio_buffer_first(const iio_buffer* b,const iio_channel* c){return const_cast<char*>(b->bytes.data()+c->index*(fault("offset")?4:2));}
ptrdiff_t iio_buffer_step(const iio_buffer*){return 4;}
ssize_t iio_device_attr_read(const iio_device*,const char* attr,char* buffer,size_t n){
 std::string a(attr),value;
 if(a=="available")value="40msps-20mhz 8msps-4mhz";
 else if(a=="active")value=profile;
 else if(a=="request_id")value=std::to_string(ticket);
 else if(a=="configuration_id")value=std::to_string(config);
 else if(a=="status")value=fault("rollback")&&ticket?"rolled_back":"applied";
 else if(a=="error")value="injected";
 else if(a=="active_info")value="{\"active\":\""+profile+"\",\"boot_id\":\"offline\",\"configuration_id\":"+std::to_string(config)+"}";
 else return -ENOENT;
 if(value.size()+1>n)return -ENOSPC;
 std::memcpy(buffer,value.c_str(),value.size()+1);return ssize_t(value.size()+1);
}
ssize_t iio_channel_attr_read(const iio_channel*,const char*,char* b,size_t n){if(n<3)return -ENOSPC;std::strcpy(b,"42");return 3;}
ssize_t iio_device_attr_write(const iio_device*,const char* attr,const char* value){
 if(std::string(attr)!="select")return -EINVAL;
 profile=value;ticket+=fault("concurrent")?2:1;config++;return ssize_t(std::strlen(value)+1);
}
}
