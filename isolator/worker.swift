// Pipe-only PCM worker. Run ONLY under worker.sb, using a verified local model.
import Foundation
import MLX
import VoiceIsolatorMLX
func exact(_ count: Int) throws -> Data {
    var data = Data()
    while data.count < count {
        guard let part = try FileHandle.standardInput.read(upToCount: count-data.count), !part.isEmpty else { throw CocoaError(.fileReadUnknown) }
        data.append(part)
    }
    return data
}
func run() throws {
    guard CommandLine.arguments.count == 2 else { exit(2) }
    GPU.set(cacheLimit: 256 << 20)
    let model = try VoiceIsolator(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]), mode: .streaming, dtype: .float16, lookaheadFrames: 2)
    // Compile kernels before READY; discard warm-up state, never mix it into a call.
    let warm = try model.stream(blockFrames: 2)
    for i in 0..<100 {
        let samples = (0..<960).map { j in Float(sin(Double(i*960+j)*0.027)*0.03) }
        _ = try warm.push(samples)
    }
    _ = try warm.flush()
    let stream = try model.stream(blockFrames: 2)
    try FileHandle.standardOutput.write(contentsOf: Data("READY\n".utf8))
    while true {
        let raw = try exact(1920)
        let samples: [Float] = raw.withUnsafeBytes { bytes in
            (0..<960).map { Float(Int16(littleEndian: bytes.loadUnaligned(fromByteOffset: $0*2, as: Int16.self))) / 32768 }
        }
        let output = try stream.push(samples)
        guard output.count <= 9600, output.allSatisfy({ $0.isFinite }) else { exit(3) }
        var header = UInt32(output.count*2).bigEndian
        var payload = Data(bytes: &header, count: 4)
        for sample in output {
            var value = Int16(max(-32768, min(32767, Int(sample*32768)))).littleEndian
            withUnsafeBytes(of: &value) { payload.append(contentsOf: $0) }
        }
        try FileHandle.standardOutput.write(contentsOf: payload)
    }
}
do { try run() } catch { exit(1) }
