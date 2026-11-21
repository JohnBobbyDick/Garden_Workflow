// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "GardenSwift",
    defaultLocalization: "ru",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        .executable(name: "GardenApp", targets: ["GardenApp"]),
        .library(name: "GardenCore", targets: ["GardenCore"])
    ],
    targets: [
        .target(name: "GardenCore"),
        .executableTarget(name: "GardenApp", dependencies: ["GardenCore"], resources: [.process("Resources")]),
        .executableTarget(name: "GardenCoreTests", dependencies: ["GardenCore"], path: "Tests/GardenCoreTests"),
        .executableTarget(name: "GardenLiveTests", dependencies: ["GardenCore"], path: "Tests/GardenLiveTests")
    ]
)
