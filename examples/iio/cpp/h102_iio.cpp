/******************************************************************************
 * Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
 * @file       h102_iio.cpp
 * @brief      Demonstrate IIO queries, configuration transactions and managed finite IQ I/O.
 * @details    C++17 RAII manages libiio 0.x resources; the Python owner launcher
 *             authorizes stages over an inherited socket. All exits destroy buffers/context.
 * @author     LogicRF Technologies
 * @architect  LogicRF
 * @email      info@logicrf.com
 * @website    https://www.logicrf.com
 * @version    1.0.0
 * @date       2026-10-16
 * @note       TX submits finite buffers with RF off; it does not prove continuous or RF TX.
 ******************************************************************************/
#include <iio.h>
#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <fcntl.h>
#include <sys/socket.h>
#include <iostream>
#include <iterator>
#include <memory>
#include <poll.h>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {
constexpr std::size_t kSamples = 65536; ///< Complex IQ16 samples; four bytes per channel sample.
using ContextPtr = std::unique_ptr<iio_context, decltype(&iio_context_destroy)>;
using BufferPtr = std::unique_ptr<iio_buffer, decltype(&iio_buffer_destroy)>;

/** @brief Preserve libiio negative errno and reject errors or short submissions. */
ssize_t checked(ssize_t result, const char* action)
{
    if (result < 0) throw std::runtime_error(std::string(action)+": "+std::strerror(int(-result)));
    return result;
}

/** @brief Request real owner authorization; stop on EOF, timeout or rejection. */
void permit(int fd)
{
    if (fd < 0) throw std::runtime_error("Run IQ commands through managed_iq.py");
    const char request = '?';
    if (::send(fd, &request, 1, MSG_NOSIGNAL) != 1) throw std::runtime_error("Owner pipe closed");
    pollfd poller{fd, POLLIN, 0};
    if (::poll(&poller, 1, 12000) != 1 || !(poller.revents & POLLIN))
        throw std::runtime_error("Owner permit timeout / EOF");
    char answer = 0;
    if (::read(fd, &answer, 1) != 1 || answer != 'Y')
        throw std::runtime_error("Owner permission denied");
}

/** @brief Own a single-threaded context; device/channel pointers borrow its lifetime. */
class Client {
public:
    explicit Client(const std::string& uri)
        : context_(nullptr, &iio_context_destroy)
    {
        unsigned major = 0, minor = 0; char tag[8]{};
        iio_library_get_version(&major, &minor, tag);
        if (major != 0 || minor < 23) throw std::runtime_error("libiio 0.x >= 0.23 required");
        context_.reset(iio_create_context_from_uri(uri.c_str()));
        if (!context_) throw std::runtime_error("Cannot create IIO context");
        checked(iio_context_set_timeout(context_.get(), 1500), "set timeout");
        device("h102-profile-control"); device("adrv9002-phy");
    }

    iio_context* context() const { return context_.get(); }

    iio_device* device(const std::string& name) const
    {
        auto* found = iio_context_find_device(context_.get(), name.c_str());
        if (!found) throw std::runtime_error("Device not found: "+name);
        return found;
    }

    /** @brief Read a text attribute, distinguishing PHY input/output channels by direction. */
    std::string read(const std::string& dev, const std::string& attr,
                     const std::string& channel = "", bool output = false) const
    {
        char buffer[16384]; auto* target = device(dev); ssize_t n;
        if (channel.empty()) n = iio_device_attr_read(target, attr.c_str(), buffer, sizeof(buffer));
        else {
            auto* ch = iio_device_find_channel(target, channel.c_str(), output);
            if (!ch) throw std::runtime_error("Channel not found");
            n = iio_channel_attr_read(ch, attr.c_str(), buffer, sizeof(buffer));
        }
        checked(n, "read attribute");
        if (std::size_t(n) >= sizeof(buffer)) throw std::runtime_error("Attribute truncated");
        std::string value(buffer, std::size_t(n));
        while (!value.empty() && (value.back()==0 || value.back()=='\n' || value.back()=='\r')) value.pop_back();
        return value;
    }

    std::string control(const std::string& name) const { return read("h102-profile-control", name); }

    /** @brief Double-read cached configuration state; queries do not authorize hardware start. */
    std::string snapshot() const
    {
        const auto status = control("status");
        const auto ticket = control("request_id"), id = control("configuration_id");
        if (status=="unavailable" || status=="queued" || status=="applying")
            throw std::runtime_error("Profile busy: "+status);
        const auto info = control("active_info");
        if (status!=control("status") || ticket!=control("request_id") || id!=control("configuration_id"))
            throw std::runtime_error("Profile changed while reading");
        return info;
    }

    /** @brief Run a single-writer transaction; report sequence conflicts and uncertain outcomes. */
    std::string select(const std::string& profile)
    {
        if (!std::regex_match(profile, std::regex("[A-Za-z0-9_.-]{1,63}")))
            throw std::runtime_error("Invalid profile ID");
        std::istringstream available(control("available")); std::string item; bool found=false;
        while (available >> item) found = found || item==profile;
        if (!found) throw std::runtime_error("Profile unavailable");
        const auto before = snapshot(); (void)before;
        if (control("active")==profile) return snapshot();
        const auto id = std::stoull(control("configuration_id"));
        const auto ticket = std::stoull(control("request_id"))+1;
        checked(iio_device_attr_write(device("h102-profile-control"), "select", profile.c_str()), "select");
        const auto deadline = std::chrono::steady_clock::now()+std::chrono::seconds(240);
        while (true) {
            if (std::stoull(control("request_id"))!=ticket)
                throw std::runtime_error("Concurrent writer: request outcome unknown");
            const auto status=control("status");
            if (status!="queued" && status!="applying") {
                if (status!="applied") throw std::runtime_error(status+": "+control("error"));
                if (control("active")!=profile || std::stoull(control("configuration_id"))<=id)
                    throw std::runtime_error("Profile readback mismatch");
                return snapshot();
            }
            if (std::chrono::steady_clock::now()>=deadline)
                throw std::runtime_error("Profile deadline: inspect state before retry");
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }

    /** @brief Require real authorization and complete transfer for one finite IQ16 buffer. */
    void transfer(bool tx, int channel, int guard, const std::string& path)
    {
        permit(guard);
        if (channel!=1 && channel!=2) throw std::runtime_error("Channel must be 1 or 2");
        const std::string name = "axi-adrv9002-"+std::string(tx ? "tx" : "rx")+(channel==2 ? "2" : "")+"-lpc";
        auto* dev = device(name);
        for (unsigned i=0; i<iio_device_get_channels_count(dev); ++i)
            iio_channel_disable(iio_device_get_channel(dev, i));
        auto* i = iio_device_find_channel(dev, tx ? "voltage0" : "voltage0_i", tx);
        auto* q = iio_device_find_channel(dev, tx ? "voltage1" : "voltage0_q", tx);
        int index=0;
        for (auto* ch : {i,q}) {
            if (!ch || iio_channel_get_index(ch)!=index++) throw std::runtime_error("Scan index");
            const auto* f=iio_channel_get_data_format(ch);
            if (!f || f->length!=16 || f->bits!=16 || f->shift || !f->is_signed || f->is_be || f->repeat!=1)
                throw std::runtime_error("Scan format is not LE signed IQ16");
            iio_channel_enable(ch);
        }
        if (iio_device_get_sample_size(dev)!=4) throw std::runtime_error("Scan sample size");
        std::vector<char> raw;
        if (tx) {
            std::ifstream file(path, std::ios::binary);
            if (!file) throw std::runtime_error("Cannot read IQ file");
            file.seekg(0,std::ios::end);
            if (file.tellg()!=std::streampos(kSamples*4)) throw std::runtime_error("TX requires 262144 bytes");
            file.seekg(0); raw.resize(kSamples*4);file.read(raw.data(),std::streamsize(raw.size()));
            if (!file) throw std::runtime_error("TX IQ file read failed");
        }
        permit(guard);
        BufferPtr buffer(iio_device_create_buffer(dev, kSamples, false), &iio_buffer_destroy);
        if (!buffer) throw std::runtime_error("Cannot create buffer");
        if (!tx && checked(iio_buffer_refill(buffer.get()), "refill")!=ssize_t(kSamples*4))
            throw std::runtime_error("Short RX refill");
        auto* begin=static_cast<char*>(iio_buffer_start(buffer.get()));
        auto* end=static_cast<char*>(iio_buffer_end(buffer.get()));
        if (iio_buffer_step(buffer.get())!=4 || end-begin!=std::ptrdiff_t(kSamples*4) ||
            iio_buffer_first(buffer.get(),i)!=begin || iio_buffer_first(buffer.get(),q)!=begin+2)
            throw std::runtime_error("Buffer layout");
        permit(guard);
        if (tx) {
            std::memcpy(begin, raw.data(), raw.size());
            if (checked(iio_buffer_push(buffer.get()), "push")!=ssize_t(raw.size()))
                throw std::runtime_error("Short TX push");
        } else {
            // Write only the wrapper's new .partial path; publish the file after owner recovery.
            const int fd=::open(path.c_str(), O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0600);
            if (fd<0) throw std::runtime_error("IQ output must be a new regular path");
            try {
                auto* position=begin;
                while (position<end) {
                    const auto n=::write(fd,position,std::size_t(end-position));
                    if (n<0 && errno==EINTR) continue;
                    if (n<=0) throw std::runtime_error("IQ file write failed");
                    position+=n;
                }
                if (::fsync(fd)) throw std::runtime_error("IQ file fsync failed");
            } catch (...) { ::close(fd); throw; }
            if (::close(fd)) throw std::runtime_error("IQ file close failed");
        }
        permit(guard);
    }
private:
    ContextPtr context_;
};
} // namespace

/** @brief Queries run independently; RX/TX require the managed_iq.py guard socket. */
int main(int argc, char** argv)
{
    try {
        if (argc==2 && std::string(argv[1])=="--help") {
            std::cout << "h102_iio URI xml|status|profiles|select ID|read DEVICE ATTR [CHANNEL in|out]\n"
                         "h102_iio workflow managed_session.py ACTION [ARGS...] (shared Python owner)\n"
                         "managed_iq.py owns RX/TX: h102_iio URI rx|tx CHANNEL FILE GUARD_FD\n";
            return 0;
        }
        if (argc>=4 && std::string(argv[1])=="workflow") {
            // Use the fixed Python recovery backend rather than duplicating the board algorithm.
            std::vector<char*> args{const_cast<char*>("python3")};
            for (int i=2;i<argc;++i) args.push_back(argv[i]);
            args.push_back(nullptr); ::execvp(args[0],args.data());
            throw std::runtime_error("Cannot exec Python workflow");
        }
        if (argc<3) throw std::runtime_error("Use --help");
        const std::string command=argv[2];
        // Reject unmanaged data commands before creating an IIO context.
        if ((command=="rx" || command=="tx") && argc!=6) throw std::runtime_error("Managed guard required");
        Client client(argv[1]);
        if (command=="xml" && argc==3) std::cout << iio_context_get_xml(client.context());
        else if (command=="status" && argc==3) std::cout << client.snapshot();
        else if (command=="profiles" && argc==3) std::cout << client.control("available");
        else if (command=="select" && argc==4) std::cout << client.select(argv[3]);
        else if (command=="read" && (argc==5 || argc==7)) {
            if (argc==7 && std::string(argv[6])!="in" && std::string(argv[6])!="out")
                throw std::runtime_error("Direction must be in or out");
            std::cout << client.read(argv[3],argv[4],argc==7 ? argv[5] : "",argc==7 && std::string(argv[6])=="out");
        } else if (command=="rx" || command=="tx") client.transfer(command=="tx",std::stoi(argv[3]),std::stoi(argv[5]),argv[4]);
        else throw std::runtime_error("Invalid command / arguments");
        std::cout << '\n'; return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
