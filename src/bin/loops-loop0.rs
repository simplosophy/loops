#[tokio::main]
async fn main() -> anyhow::Result<()> {
    std::process::exit(loops::loop0::cli::main().await);
}
