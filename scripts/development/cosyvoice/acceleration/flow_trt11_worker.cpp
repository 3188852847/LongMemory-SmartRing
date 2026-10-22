// SDK11独立进程。只以CPU FP32管道交换数据，不跨CUDA12/13运行时共享设备指针。
#include <NvInferRuntime.h>
#include <NvInferPlugin.h>
#include <cuda_runtime_api.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <io.h>
#include <fcntl.h>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

struct Logger : nvinfer1::ILogger {
    void log(Severity severity, char const* message) noexcept override {
        if (severity <= Severity::kWARNING) std::fprintf(stderr, "%s\n", message);
    }
};
static void check(cudaError_t result) {
    if (result != cudaSuccess) throw std::runtime_error(cudaGetErrorString(result));
}
static void require(bool value, char const* message) {
    if (!value) throw std::runtime_error(message);
}
static void read(void* target, size_t bytes) {
    require(std::fread(target, 1, bytes, stdin) == bytes, "incomplete Flow request");
}
static void respond(char const* magic, uint32_t status, void const* payload, uint32_t bytes) {
    std::fwrite(magic, 1, 4, stdout);
    std::fwrite(&status, sizeof(status), 1, stdout);
    std::fwrite(&bytes, sizeof(bytes), 1, stdout);
    if (bytes) std::fwrite(payload, 1, bytes, stdout);
    std::fflush(stdout);
}
struct Stream {
    cudaStream_t value{};
    Stream() { check(cudaStreamCreateWithFlags(&value, cudaStreamNonBlocking)); }
    ~Stream() { if (value) cudaStreamDestroy(value); }
};
struct Buffers {
    std::array<void*, 7> data{};
    ~Buffers() { for (auto pointer : data) if (pointer) cudaFree(pointer); }
};

int wmain(int argc, wchar_t** argv) {
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    bool ready = false;
    try {
        require(argc == 2, "usage: flow_trt11_worker.exe engine.plan");
        std::ifstream input(std::filesystem::path(argv[1]), std::ios::binary | std::ios::ate);
        require(input.good(), "cannot open Flow engine");
        auto size = input.tellg();
        require(size > 0, "empty Flow engine");
        std::vector<char> serialized(static_cast<size_t>(size));
        input.seekg(0);
        require(static_cast<bool>(input.read(serialized.data(), serialized.size())), "cannot read Flow engine");
        Logger logger;
        initLibNvInferPlugins(&logger, "");
        std::unique_ptr<nvinfer1::IRuntime> runtime(nvinfer1::createInferRuntime(logger));
        require(static_cast<bool>(runtime), "cannot create TensorRT11 runtime");
        std::unique_ptr<nvinfer1::ICudaEngine> engine(runtime->deserializeCudaEngine(serialized.data(), serialized.size()));
        require(static_cast<bool>(engine), "cannot deserialize Flow engine");
        serialized.clear(); serialized.shrink_to_fit();
        std::unique_ptr<nvinfer1::IExecutionContext> context(engine->createExecutionContext());
        require(static_cast<bool>(context), "cannot create Flow execution context");
        constexpr char const* names[] = {"x", "mask", "mu", "t", "spks", "cond", "estimator_out"};
        require(engine->getNbIOTensors() == 7, "Flow engine must have six inputs and one output");
        for (auto name : names) require(engine->getTensorDataType(name) == nvinfer1::DataType::kFLOAT, "Flow engine must be FP32");
        Stream stream;
        Buffers buffers;
        std::array<size_t, 7> maximum = {160*512, 2*512, 160*512, 2, 160, 160*512, 160*512};
        for (int i = 0; i < 7; ++i) {
            check(cudaMalloc(&buffers.data[i], maximum[i]*sizeof(float)));
            require(context->setTensorAddress(names[i], buffers.data[i]), "cannot bind Flow tensor");
        }
        respond("RDY1", 0, nullptr, 0);
        ready = true;
        while (true) {
            char magic[4];
            auto got = std::fread(magic, 1, 4, stdin);
            if (!got) break;
            require(got == 4 && std::memcmp(magic, "FLW1", 4) == 0, "invalid Flow request");
            uint32_t n;
            read(&n, sizeof(n));
            require(n >= 16 && n <= 512, "Flow sequence outside engine profile");
            auto length = static_cast<int64_t>(n);
            std::array<nvinfer1::Dims, 6> shapes = {
                nvinfer1::Dims{3,{2,80,length}}, nvinfer1::Dims{3,{2,1,length}},
                nvinfer1::Dims{3,{2,80,length}}, nvinfer1::Dims{1,{2}},
                nvinfer1::Dims{2,{2,80}}, nvinfer1::Dims{3,{2,80,length}}};
            std::array<size_t, 6> counts = {160*n, 2*n, 160*n, 2, 160, 160*n};
            std::array<std::vector<float>, 6> values;
            for (int i = 0; i < 6; ++i) {
                require(context->setInputShape(names[i], shapes[i]), "cannot set Flow input shape");
                values[i].resize(counts[i]);
                read(values[i].data(), counts[i]*sizeof(float));
                check(cudaMemcpyAsync(buffers.data[i], values[i].data(), counts[i]*sizeof(float), cudaMemcpyHostToDevice, stream.value));
            }
            auto outputShape = context->getTensorShape("estimator_out");
            require(outputShape.nbDims == 3 && outputShape.d[0] == 2 && outputShape.d[1] == 80 && outputShape.d[2] == n,
                    "Flow output shape differs from request");
            require(context->enqueueV3(stream.value), "Flow TensorRT enqueue failed");
            std::vector<float> output(160*n);
            check(cudaMemcpyAsync(output.data(), buffers.data[6], output.size()*sizeof(float), cudaMemcpyDeviceToHost, stream.value));
            check(cudaStreamSynchronize(stream.value));
            respond("FLW1", 0, output.data(), static_cast<uint32_t>(output.size()*sizeof(float)));
        }
        return 0;
    } catch (std::exception const& error) {
        auto message = std::string(error.what());
        respond(ready ? "FLW1" : "RDY1", 1, message.data(), static_cast<uint32_t>(message.size()));
        return 1;
    }
}
