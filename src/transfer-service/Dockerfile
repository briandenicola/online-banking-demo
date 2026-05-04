FROM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS build
WORKDIR /src

# Copy shared Contracts project
COPY src/shared/Contracts/*.csproj ./shared/Contracts/
RUN dotnet restore "./shared/Contracts/Contracts.csproj"

# Copy transfer-service project
COPY src/transfer-service/*.csproj ./transfer-service/
RUN dotnet restore "./transfer-service/transfer-service.csproj"

# Copy everything else
COPY src/shared/Contracts/. ./shared/Contracts/
COPY src/transfer-service/. ./transfer-service/

WORKDIR /src/transfer-service
RUN dotnet publish -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:9.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "transfer-service.dll"]